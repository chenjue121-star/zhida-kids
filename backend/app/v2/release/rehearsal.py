"""SQLite-only migration, backup, local switch and rollback evidence.

All outputs must be new directories. No application config, MySQL DSN, old
database, model provider, remote image or deployed process is accepted here.
"""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.v2.core.config import V2Settings
from app.v2.main import create_app
from app.v2.outfits.models import OutfitPlan
from app.v2.release.legacy import import_legacy
from app.v2.release.models import LegacySourceRecord

ROOT = Path(__file__).resolve().parents[3]
HEAD = '0005_personalization_calendar'


def _fresh_directory(path):
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError('Output must be a new isolated directory')
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Output parents must not be symlinks')
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    path.chmod(0o600)


def _regular_file(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Backup paths must not contain a symlink')
    if not path.is_file():
        raise ValueError('Backup file is missing or not regular')


def _files(root):
    root = Path(root)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError('Media directory must not be a symlink')
    if not root.is_dir():
        raise ValueError('Media directory must exist')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Media tree contains a symlink')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Media tree contains a nonregular file')
        result[path.relative_to(root).as_posix()] = path
    return result


def _file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_private(source, target):
    created = []
    parent = target.parent
    while not parent.exists():
        created.append(parent)
        parent = parent.parent
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    for directory in created:
        directory.chmod(0o700)
    shutil.copyfile(source, target)
    target.chmod(0o600)


def database_fingerprint(database_path):
    path = Path(database_path).absolute()
    _regular_file(path)
    digest = sha256()
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite integrity check failed')
            schema_objects = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
            digest.update(json.dumps(schema_objects, ensure_ascii=False, separators=(',', ':')).encode())
            tables = connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            for name, schema in tables:
                quoted = '"' + name.replace('"', '""') + '"'
                rows = connection.execute('SELECT * FROM ' + quoted).fetchall()
                serialized = [json.dumps(row, ensure_ascii=False, separators=(',', ':'), default=lambda value: {'bytes': value.hex()}) for row in rows]
                digest.update(json.dumps([name, schema, sorted(serialized)], ensure_ascii=False, separators=(',', ':')).encode())
    except sqlite3.DatabaseError:
        raise ValueError('SQLite integrity check failed') from None
    return digest.hexdigest()


def backup_bundle(database_path, media_dir, bundle_dir):
    database_path, media_dir = Path(database_path).absolute(), Path(media_dir).absolute()
    _regular_file(database_path)
    media = _files(media_dir)
    fingerprint = database_fingerprint(database_path)
    bundle = _fresh_directory(bundle_dir)
    if bundle.is_relative_to(media_dir):
        bundle.rmdir()
        raise ValueError('Backup output must be outside the media tree')
    backup_db = bundle / 'database.sqlite'
    with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup_db) as destination:
            source.backup(destination)
    backup_db.chmod(0o600)
    (bundle / 'media').mkdir(mode=0o700)
    for relative, path in media.items():
        _copy_private(path, bundle / 'media' / relative)
    # A writer changing DB/media during this snapshot invalidates the rehearsal.
    if fingerprint != database_fingerprint(backup_db):
        raise ValueError('Database changed during backup; stop writes and retry with a new directory')
    files = {'database.sqlite': {'sha256': _file_hash(backup_db), 'bytes': backup_db.stat().st_size}}
    for relative, path in media.items():
        copied = bundle / 'media' / relative
        if _file_hash(path) != _file_hash(copied):
            raise ValueError('Media changed during backup; stop writes and retry')
        files['media/' + relative] = {'sha256': _file_hash(copied), 'bytes': copied.stat().st_size}
    manifest = {'schema_version': 1, 'engine': 'sqlite', 'database_fingerprint': fingerprint, 'files': files}
    _write_json(bundle / 'manifest.json', manifest)
    return manifest


def _verify_bundle(bundle_dir):
    bundle = Path(bundle_dir).absolute()
    _regular_file(bundle / 'manifest.json')
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('engine') != 'sqlite' or not isinstance(manifest.get('files'), dict):
        raise ValueError('Backup manifest format is invalid')
    if 'database.sqlite' not in manifest['files']:
        raise ValueError('Backup manifest must include its database')
    for relative, item in manifest['files'].items():
        safe = PurePosixPath(relative)
        if safe.is_absolute() or '..' in safe.parts or safe.as_posix() != relative or not (relative == 'database.sqlite' or relative.startswith('media/')):
            raise ValueError('Backup manifest path is unsafe')
        path = bundle / relative
        _regular_file(path)
        if not isinstance(item, dict) or _file_hash(path) != item.get('sha256') or path.stat().st_size != item.get('bytes'):
            raise ValueError('Backup hash mismatch; refusing restore')
    actual = set(_files(bundle))
    if actual != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('Backup file inventory drift')
    if database_fingerprint(bundle / 'database.sqlite') != manifest.get('database_fingerprint'):
        raise ValueError('Backup database fingerprint mismatch')
    return bundle, manifest


def restore_bundle(bundle_dir, output_dir):
    bundle, manifest = _verify_bundle(bundle_dir)
    if Path(output_dir).absolute().resolve().is_relative_to(bundle.resolve()):
        raise ValueError('Restore output must be outside the backup directory')
    restored = _fresh_directory(output_dir)
    (restored / 'media').mkdir(mode=0o700)
    for relative in manifest['files']:
        _copy_private(bundle / relative, restored / relative)
    verify_restored(bundle, restored)
    return {'database_path': str(restored / 'database.sqlite'), 'media_dir': str(restored / 'media')}


def verify_restored(bundle_dir, restored_dir):
    _, manifest = _verify_bundle(bundle_dir)
    restored = Path(restored_dir).absolute()
    actual = set(_files(restored))
    if actual != set(manifest['files']):
        raise ValueError('Restore file inventory drift')
    if database_fingerprint(restored / 'database.sqlite') != manifest['database_fingerprint']:
        raise ValueError('Restore database drift')
    for relative, item in manifest['files'].items():
        if relative.startswith('media/') and _file_hash(restored / relative) != item['sha256']:
            raise ValueError('Restore media drift')
    return True


def _alembic(database, revision):
    config = Config(str(ROOT / 'alembic-v2.ini'))
    config.attributes['database_url'] = 'sqlite:///' + str(database)
    command.upgrade(config, revision)


def _ready(database, media):
    engine = create_engine('sqlite:///' + str(database))
    settings = V2Settings(_env_file=None, database_url='sqlite:///' + str(database), env='test',
                          jwt_secret='isolated-rehearsal-secret-at-least-32-characters',
                          private_storage_dir=str(media), recognition_provider='disabled', outfit_provider='disabled')
    try:
        with TestClient(create_app(settings, engine)) as client:
            return client.get('/ready').status_code
    finally:
        engine.dispose()


def run_rehearsal(source_path, output_dir):
    source_path = Path(source_path).absolute()
    _regular_file(source_path)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if source.get('synthetic') is not True:
        raise ValueError('This rehearsal command requires an explicitly synthetic export; real historical migration remains a separate decision')
    output = _fresh_directory(output_dir)
    database, media = output / 'release.sqlite', output / 'private-media'
    media.mkdir(mode=0o700)
    (media / 'synthetic-backup-fixture.bin').write_bytes(b'Phase D synthetic private-media backup fixture\n')
    (media / 'synthetic-backup-fixture.bin').chmod(0o600)
    _alembic(database, '0004_daily_outfits')
    before_migration = _ready(database, media)
    backup_bundle(database, media, output / 'before-migration')
    _alembic(database, 'head')
    database.chmod(0o600)
    engine = create_engine('sqlite:///' + str(database))
    with Session(engine) as db, db.begin():
        imported = import_legacy(db, source, 'phase-d-synthetic-v1')
        repeated = import_legacy(db, source, 'phase-d-synthetic-v1')
        diary_count = db.scalar(select(func.count()).select_from(LegacySourceRecord).where(LegacySourceRecord.entity == 'outfit_diaries'))
        plan_count = db.scalar(select(func.count()).select_from(OutfitPlan))
    engine.dispose()
    ready_before = _ready(database, media)
    backup_bundle(database, media, output / 'validated-release')
    _write_json(output / 'active-simulation.json', {'stage': 'release', 'database_path': str(database), 'private_media': str(media)})
    # Emulate post-switch data changes, then recover the approved DB/media snapshot.
    engine = create_engine('sqlite:///' + str(database))
    with engine.begin() as db:
        db.execute(text("UPDATE users SET nickname='synthetic post-switch change'"))
    engine.dispose()
    restored = restore_bundle(output / 'validated-release', output / 'rollback-restored')
    matches = verify_restored(output / 'validated-release', output / 'rollback-restored')
    ready_after = _ready(Path(restored['database_path']), Path(restored['media_dir']))
    _write_json(output / 'active-simulation.json', {'stage': 'rollback', **restored})
    old_schema = restore_bundle(output / 'before-migration', output / 'before-migration-restored')
    old_ready = _ready(Path(old_schema['database_path']), Path(old_schema['media_dir']))
    engine = create_engine('sqlite:///' + restored['database_path'])
    with engine.connect() as db:
        head = db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    engine.dispose()
    if (before_migration, ready_before, ready_after, old_ready) != (503, 200, 200, 503) or head != HEAD or plan_count != 0:
        raise ValueError('Release/rollback readiness or source-only diary assertion failed')
    report = {'status': 'passed', 'engine': 'sqlite', 'source_kind': 'synthetic', 'source_sha256': _file_hash(source_path),
              'head': head, 'ready_before_migration': before_migration, 'ready_before_release': ready_before,
              'ready_after_restore': ready_after, 'prior_schema_ready_with_d_app': old_ready,
              'imported': imported['imported'], 'reimport_reused': repeated['reused'],
              'legacy_source_diaries': diary_count, 'legacy_diaries_converted': plan_count,
              'remote_assets_fetched': 0, 'restored_matches_backup': matches,
              'restore_media_bytes_verified': True, 'real_deployment_performed': False,
              'real_mysql_data_restore_verified': False, 'model_calls': 0,
              'limitations': ['SQLite rehearsal does not replace MySQL populated backup/restore verification',
                              'Prior schema requires its matching prior application version',
                              'Synthetic backup bytes are not migrated legacy image assets',
                              'Real historical migration, HTTPS deployment and device acceptance remain pending']}
    _write_json(output / 'report.json', report)
    return report
