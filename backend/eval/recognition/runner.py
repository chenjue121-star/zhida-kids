from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.services.recognition.recognize import recognize_image

# recognizer 签名：async (image_data_url: str, prompt_text: str) -> ClothingRecognizeOut
Recognizer = Callable[[str, str], Awaitable[object]]


def cache_key(image_name: str, prompt_text: str, run_index: int) -> str:
    h = hashlib.sha256()
    h.update(image_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(run_index).encode("utf-8"))
    return h.hexdigest()[:32]


def _image_to_data_url(image_path: Path) -> str:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def run_recognition(
    image_path: Path,
    image_name: str,
    prompt_text: str,
    run_index: int,
    cache_dir: Path,
    recognizer: Optional[Recognizer] = None,
    use_cache: bool = True,
) -> dict:
    """返回归一化后的识别 dict（ClothingRecognizeOut.model_dump 的子集）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key(image_name, prompt_text, run_index)}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    fn = recognizer or recognize_image
    data_url = _image_to_data_url(image_path)
    result = await fn(data_url, prompt_text)
    payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
