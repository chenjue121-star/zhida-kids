from importlib.util import find_spec
import os
import subprocess
import sys
import pytest
from pydantic import ValidationError


def test_v2_factory_exists_without_importing_old_app():
    assert find_spec('app.v2') is not None, 'isolated v2 application is missing'
    from app.v2.main import create_app
    assert callable(create_app)


def test_health_ready_without_schema(client):
    assert client.get('/health').status_code == 200
    response = client.get('/ready')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'NOT_READY'


def test_config_isolation(monkeypatch):
    from app.v2.core.config import V2Settings, BACKEND_ROOT
    for name in list(os.environ):
        if name.startswith('V2_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('JWT_SECRET', 'legacy')
    with pytest.raises(ValidationError):
        V2Settings(_env_file=None)
    assert BACKEND_ROOT.name == 'backend'
    with pytest.raises(ValidationError, match='production'):
        V2Settings(_env_file=None, database_url='sqlite://', jwt_secret='secret', env='production', dev_wechat_mock=True)


def test_import_does_not_connect_or_import_old_services():
    script = '''
import sqlalchemy, sys
def forbidden(*args, **kwargs):
    raise AssertionError('Import attempted engine creation')
sqlalchemy.create_engine = forbidden
from app.v2.main import create_app
from app.v2.core.database import load_metadata
assert len(load_metadata().tables) == 25
assert not any(name in sys.modules for name in ['app.main', 'app.database', 'app.models', 'app.config'])
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_http_errors_use_error_contract(client):
    response = client.get('/v2/no-such-route')
    assert response.status_code == 404
    assert response.json()['error']['request_id'] == response.headers['X-Request-ID']
