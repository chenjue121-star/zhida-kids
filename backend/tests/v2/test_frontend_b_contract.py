"""Exercise the shipped native JS services against real HTTP routes, without external APIs."""
import base64
import io
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

from PIL import Image
import uvicorn


def test_native_phase_b_services_against_real_http(engine, tmp_path):
    from app.v2.core.config import V2Settings
    from app.v2.main import create_app
    node = shutil.which('node')
    assert node, 'Node is required for the native client/server contract test'
    settings = V2Settings(_env_file=None, database_url='sqlite://',
        jwt_secret='contract-test-secret-at-least-thirty-two-bytes', env='test',
        recognition_provider='disabled', private_storage_dir=str(tmp_path / 'media'))
    app = create_app(settings, engine, lambda code: {'openid': code, 'nickname': code})
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        output = io.BytesIO()
        Image.new('RGB', (40, 60), 'white').save(output, format='PNG')
        script = Path(__file__).resolve().parents[3] / 'miniprogram-v2/tests/phase-b-contract-smoke.js'
        result = subprocess.run([node, str(script), f'http://127.0.0.1:{port}/v2',
            base64.b64encode(output.getvalue()).decode()], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '"status":"passed"' in result.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
