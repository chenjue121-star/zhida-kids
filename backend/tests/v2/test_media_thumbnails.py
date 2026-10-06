from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import select

from app.v2.families.models import Membership
from app.v2.media.models import MediaAsset
from app.v2.media.storage import FileStorage
from app.v2.wardrobe.models import Clothing
from test_b_wardrobe_intake import batch, child, confirm


def upload_photo(client, family, user, auth, tmp_path, *, size=(1200, 800)):
    client.app.state.storage = FileStorage(tmp_path)
    root = '/v2/families/' + family['id']
    headers = auth(user)
    kid = child(client, root, headers)
    intake = batch(client, root, headers, kid['id'])
    path = root + '/intake/batches/' + intake['id']
    item = client.post(path + '/items', headers=headers,
        json={'client_id': uuid4().hex, 'source': 'album'}).json()
    source = BytesIO()
    Image.new('RGB', size, 'blue').save(source, format='PNG')
    uploaded = client.put(path + '/items/' + item['id'] + '/upload',
        headers={**headers, 'Content-Type': 'image/png'}, content=source.getvalue())
    assert uploaded.status_code == 200, uploaded.text
    return root, headers, intake, uploaded.json(), path


def asset_path(root, item, representation='thumbnail'):
    return root + '/assets/' + item['asset_id'] + '/' + representation


@pytest.mark.parametrize('size, expected', [((1200, 800), (360, 240)), ((240, 160), (240, 160))])
def test_thumbnail_is_small_private_jpeg_without_changing_original(
        client, family_factory, auth, tmp_path, size, expected):
    family, users = family_factory()
    root, headers, _, item, _ = upload_photo(client, family, users[0], auth, tmp_path, size=size)
    original = client.get(asset_path(root, item, 'content'), headers=headers)
    assert original.status_code == 200
    with client.app.state.session_factory() as db:
        before = db.get(MediaAsset, int(item['asset_id']))
        original_key, original_sha = before.object_key, before.sha256
        asset_count = len(db.scalars(select(MediaAsset)).all())
    response = client.get(asset_path(root, item), headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/jpeg'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    with Image.open(BytesIO(response.content)) as thumbnail:
        assert thumbnail.format == 'JPEG'
        assert thumbnail.size == expected
        assert not thumbnail.getexif()
    after = client.get(asset_path(root, item, 'content'), headers=headers)
    assert after.content == original.content
    assert sha256(after.content).hexdigest() == original_sha
    assert client.app.state.storage.get(original_key) == original.content
    with client.app.state.session_factory() as db:
        assert len(db.scalars(select(MediaAsset)).all()) == asset_count
        assert db.get(MediaAsset, int(item['asset_id'])).sha256 == original_sha


def test_thumbnail_strips_source_exif_and_orients_pixels(
        client, family_factory, auth, tmp_path):
    family, users = family_factory()
    root, headers, _, item, _ = upload_photo(client, family, users[0], auth, tmp_path)
    source = BytesIO()
    image = Image.new('RGB', (800, 1200), 'blue')
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = 'private metadata'
    image.save(source, format='JPEG', exif=exif)
    stored = client.app.state.storage

    class ExifStorage:
        def get(self, key):
            stored.get(key)
            return source.getvalue()

    client.app.state.storage = ExifStorage()
    response = client.get(asset_path(root, item), headers=headers)
    assert response.status_code == 200, response.text
    with Image.open(BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (360, 240)
        assert not thumbnail.getexif()


def test_thumbnail_uses_same_draft_and_confirmed_acl_as_original(
        client, family_factory, auth, tmp_path):
    family, users = family_factory(('admin', 'editor', 'viewer'))
    root, headers, intake, item, path = upload_photo(client, family, users[0], auth, tmp_path)
    assert client.get(asset_path(root, item), headers=headers).status_code == 200
    for user in users[1:]:
        assert client.get(asset_path(root, item), headers=auth(user)).status_code == 404
    other_family, outsiders = family_factory()
    other_root = '/v2/families/' + other_family['id']
    assert client.get(asset_path(other_root, item), headers=auth(outsiders[0])).status_code == 404
    assert client.get(asset_path(root, item), headers=auth(outsiders[0])).status_code == 404
    assert client.get(asset_path(root, item)).status_code == 401
    candidate = client.post(path + '/candidates', headers=headers, json={
        'client_id': uuid4().hex, 'item_id': item['id'], 'category': 'top', 'selected': True}).json()
    assert confirm(client, root, headers, intake, [candidate]).status_code == 200
    for user in users:
        assert client.get(asset_path(root, item), headers=auth(user)).status_code == 200


def change_membership(client, family, user, *, role=None, status=None):
    with client.app.state.session_factory() as db:
        member = db.scalar(select(Membership).where(
            Membership.family_id == int(family['id']), Membership.user_id == int(user['user']['id'])))
        if role is not None:
            member.role = role
        if status is not None:
            member.status = status
        db.commit()


@pytest.mark.parametrize('phase', ['storage', 'processing'])
@pytest.mark.parametrize('change', ['revoked', 'viewer'])
def test_thumbnail_rechecks_draft_permission_after_slow_work(
        client, family_factory, auth, tmp_path, monkeypatch, phase, change):
    family, users = family_factory(('admin', 'editor'))
    root, headers, _, item, _ = upload_photo(client, family, users[1], auth, tmp_path)
    assert client.get(asset_path(root, item), headers=headers).status_code == 200

    def revoke():
        change_membership(client, family, users[1],
            role='viewer' if change == 'viewer' else None,
            status='removed' if change == 'revoked' else None)

    if phase == 'storage':
        stored = client.app.state.storage

        class DelayedStorage:
            def get(self, key):
                data = stored.get(key)
                revoke()
                return data

        client.app.state.storage = DelayedStorage()
    else:
        resize = Image.Image.thumbnail

        def delayed_resize(image, *args, **kwargs):
            resize(image, *args, **kwargs)
            revoke()

        monkeypatch.setattr(Image.Image, 'thumbnail', delayed_resize)
    response = client.get(asset_path(root, item), headers=headers)
    assert response.status_code == 404, response.text
    assert response.headers['content-type'] == 'application/json'


def test_thumbnail_rechecks_confirmed_reference_after_processing(
        client, family_factory, auth, tmp_path, monkeypatch):
    family, users = family_factory(('admin', 'viewer'))
    root, headers, intake, item, path = upload_photo(client, family, users[0], auth, tmp_path)
    candidate = client.post(path + '/candidates', headers=headers, json={
        'client_id': uuid4().hex, 'item_id': item['id'], 'category': 'top', 'selected': True}).json()
    assert confirm(client, root, headers, intake, [candidate]).status_code == 200
    viewer = auth(users[1])
    assert client.get(asset_path(root, item), headers=viewer).status_code == 200
    resize = Image.Image.thumbnail

    def remove_confirmed_reference(image, *args, **kwargs):
        resize(image, *args, **kwargs)
        with client.app.state.session_factory() as db:
            for garment in db.scalars(select(Clothing).where(Clothing.asset_id == int(item['asset_id']))):
                garment.asset_id = None
            db.commit()

    monkeypatch.setattr(Image.Image, 'thumbnail', remove_confirmed_reference)
    response = client.get(asset_path(root, item), headers=viewer)
    assert response.status_code == 404, response.text
