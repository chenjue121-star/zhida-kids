# backend/app/services/recognition/recognize.py
from __future__ import annotations

import json
import logging

import httpx

from ...config import settings
from ...schemas import ClothingRecognizeOut
from .ark_client import _compact_ark_request
from .normalize import _normalize_recognition
from .parsing import _extract_ark_text, _extract_json, _pick_recognition_object

logger = logging.getLogger(__name__)


class RecognitionError(Exception):
    """识别失败的基类。"""


class RecognitionUpstreamError(RecognitionError):
    """ARK 调用失败（网络/HTTP）。"""


class RecognitionEmptyError(RecognitionError):
    """ARK 未返回可用文本。"""


async def recognize_image(image_url: str, prompt_text: str) -> ClothingRecognizeOut:
    """调用 ARK 识别单张图片并归一化为 ClothingRecognizeOut。

    image_url: 直接可用的图片 URL 或 data url（调用方负责转换）。
    prompt_text: 识别提示词文本（生产用 _recognition_prompt()，评估用变体）。
    """
    request_body = {
        "model": settings.ark_clothing_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": image_url},
                    {"type": "input_text", "text": prompt_text},
                ],
            }
        ],
    }
    logger.warning("ark clothing request=%s", json.dumps(_compact_ark_request(request_body), ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                settings.ark_responses_url,
                headers={
                    "Authorization": f"Bearer {settings.ark_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            logger.warning("ark clothing status_code=%s", response.status_code)
            logger.warning("ark clothing response=%s", response.text[:3000])
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RecognitionUpstreamError(str(exc)) from exc

    text = _extract_ark_text(data)
    if not text:
        raise RecognitionEmptyError("AI 识别服务未返回文本")
    logger.warning("ark clothing text=%s", text[:3000])
    result = _normalize_recognition(_pick_recognition_object(_extract_json(text)))
    logger.warning("ark clothing normalized=%s", result.model_dump_json())
    return result
