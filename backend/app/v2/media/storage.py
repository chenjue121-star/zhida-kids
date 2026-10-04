from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Protocol

from app.v2.core.errors import fail


class PrivateStorage(Protocol):
    def put(self, family_id: int, digest: str, content: bytes) -> str: ...
    def get(self, object_key: str) -> bytes: ...


class FileStorage:
    """Private development storage; HTTP access must pass the asset ACL route.

    Construct with FileStorage(settings.media_root). Never mount this root as a
    public static directory. Storage keys are server-generated, family-scoped.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, object_key: str) -> Path:
        match = re.fullmatch(r'families/[1-9][0-9]*/([0-9a-f]{2})/([0-9a-f]{64})\.jpg', object_key)
        if not match or match[1] != match[2][:2]:
            fail(422, 'INVALID_ASSET_KEY', '照片存储标识无效')
        path = self.root
        for part in Path(object_key).parts:
            path /= part
            # A link into a different family is unsafe even when its target is
            # inside the same storage root. Keys must retain their own scope.
            if path.is_symlink():
                fail(422, 'INVALID_ASSET_KEY', '照片存储标识无效')
        path = path.resolve()
        if not path.is_relative_to(self.root):
            fail(422, 'INVALID_ASSET_KEY', '照片存储标识无效')
        return path

    def put(self, family_id: int, digest: str, content: bytes) -> str:
        if type(family_id) is not int or family_id <= 0 or not re.fullmatch(r'[0-9a-f]{64}', digest):
            fail(422, 'INVALID_ASSET_KEY', '照片存储标识无效')
        if hashlib.sha256(content).hexdigest() != digest:
            fail(422, 'INVALID_ASSET_HASH', '照片校验失败，请重新上传')
        key = f'families/{family_id}/{digest[:2]}/{digest}.jpg'
        path = self._path(key)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent = self.root
        for part in Path(key).parts[:-1]:
            parent /= part
            parent.mkdir(exist_ok=True, mode=0o700)
            if not parent.resolve().is_relative_to(self.root):
                fail(422, 'INVALID_ASSET_KEY', '照片存储标识无效')
        path = self._path(key)
        # Publish a fully written 0600 file without replacing another writer's
        # asset. Same-family equal hashes refer to these exact verified bytes.
        fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.get(key) != content:
                    fail(409, 'ASSET_STORAGE_CONFLICT', '照片存储校验不一致，请联系管理员')
        finally:
            Path(temporary).unlink(missing_ok=True)
        return key

    def get(self, object_key: str) -> bytes:
        path = self._path(object_key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            fail(404, 'ASSET_NOT_FOUND', '照片不存在或暂时无法读取')
