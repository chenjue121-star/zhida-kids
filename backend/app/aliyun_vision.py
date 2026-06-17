"""阿里云视觉智能开放平台（VIAPI）封装。

当前提供两个能力：
- SegmentCloth  : 服饰抠图（把衣服主体从背景中分离出来）
- ClassifyClothing : 服饰属性识别（类别、颜色、图案等）

文档：
- 抠图       : https://help.aliyun.com/zh/viapi/developer-reference/segmentcloth
- 服饰识别    : https://help.aliyun.com/zh/viapi/developer-reference/classifyclothing

调用入参既支持图片 URL，也支持 base64（ImageURL / ImageURL 参数二选一）。
为了和现有上传链路更好地结合，这里默认走 "公网可访问 URL" 入参。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict

from fastapi import HTTPException, status

from .config import settings

logger = logging.getLogger(__name__)


# ---------- client ----------

def _ensure_credentials() -> None:
    if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置阿里云视觉智能 AccessKey",
        )


def _build_client():
    """构造阿里云 VIAPI client。懒加载，避免导入即报缺少依赖。"""
    try:
        from aliyunsdkcore.client import AcsClient
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未安装阿里云视觉智能 SDK：pip install aliyun-python-sdk-viapi",
        ) from exc

    return AcsClient(
        settings.aliyun_access_key_id,
        settings.aliyun_access_key_secret,
        settings.aliyun_viapi_region or "cn-shanghai",
    )


def _call(endpoint_cls_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """通用调用入口：通过反射构造 request 并发起调用。

    这里选择按 "动态 import + 设置 set_ImageURL" 的方式调用，
    以便无需为每一个能力都单独 import 对应的 request 类。
    """
    log_params = {
        k: v if not (isinstance(v, str) and len(v) > 512) else f"<base64 {len(v)} chars>"
        for k, v in params.items()
    }
    logger.warning(
        "[aliyun_viapi] >> REQUEST endpoint=%s params=%s",
        endpoint_cls_name,
        json.dumps(log_params, ensure_ascii=False),
    )

    client = _build_client()
    try:
        mod = __import__("aliyunsdkviapi.requests.v20230417." + endpoint_cls_name, fromlist=[endpoint_cls_name])
        req_cls = getattr(mod, endpoint_cls_name)
    except (ImportError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"未找到阿里云 VIAPI 能力定义：{endpoint_cls_name}",
        ) from exc

    request = req_cls()
    request.set_accept_format("json")
    for key, value in params.items():
        setter = f"set_{key}"
        if hasattr(request, setter):
            getattr(request, setter)(value)
        else:
            # 兜底：如果 SDK 没有这个 setter，就直接 set_body_params（兼容老版本）
            try:
                request.add_body_params(key, value)
            except Exception:
                logger.warning("viapi cannot set param %s on %s", key, endpoint_cls_name)

    try:
        raw = client.do_action_with_exception(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("viapi %s call failed", endpoint_cls_name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"阿里云视觉智能调用失败：{exc.__class__.__name__}",
        ) from exc

    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("[aliyun_viapi] << RAW(first 1200 chars)=%r", str(raw)[:1200])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="阿里云视觉智能返回结果不是合法 JSON",
        ) from exc

    logger.warning(
        "[aliyun_viapi] << RESPONSE endpoint=%s payload=%s",
        endpoint_cls_name,
        json.dumps(payload, ensure_ascii=False)[:2000],
    )

    # 统一的错误字段：Code != "OK" 视为失败
    code = str(payload.get("Code") or payload.get("code") or "OK")
    if code.lower() not in {"ok", "200", ""}:
        message = str(payload.get("Message") or payload.get("message") or "")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"阿里云视觉智能返回错误：Code={code}, Message={message}",
        )
    return payload


# ---------- 抠图 ----------

def segment_cloth(image_url: str | None = None, image_base64: str | None = None) -> bytes:
    """调用 SegmentCloth 对服饰进行抠图，返回抠图后的 PNG（bytes）。

    通常两个入参二选一：如果提供了 URL 就走 URL，否则走 base64。
    """
    _ensure_credentials()

    params: Dict[str, Any] = {}
    if image_url:
        params["ImageURL"] = image_url
    elif image_base64:
        # 部分能力用 BodyURL/Body，这里统一走 ImageBodyBase64（具体以实际 SDK 为准）
        params["ImageBody"] = image_base64
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少图片源")

    payload = _call("SegmentClothRequest", params)
    data = payload.get("Data") or payload.get("data") or {}
    result = data.get("ResultImage") or data.get("Image") or payload.get("ResultImage")
    if not result or not isinstance(result, str):
        logger.warning("viapi SegmentCloth raw=%s", json.dumps(payload, ensure_ascii=False)[:800])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="抠图结果为空")
    try:
        return base64.b64decode(result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="抠图返回的 base64 解析失败",
        ) from exc


# ---------- 服饰属性识别 ----------

_CLOTHING_FIELD_MAP: Dict[str, str] = {
    # 阿里云字段名 -> 我们内部字段名
    "Category": "type",          # 服饰主类别，如 "上衣"
    "CategorySub": "sub_type",   # 服饰子类别，如 "T恤"
    "Color": "main_color",       # 主颜色，如 "红色"
    "Pattern": "pattern",        # 图案，如 "条纹"
    "Season": "season",          # 季节，如 "春秋"
    "Style": "style_tags",       # 风格，如 "休闲"
    "Texture": "thickness",      # 材质/厚度（粗略映射到 thickness）
    "Sleeve": "sleeve",          # 袖长（保留，便于后续扩展）
    "Brand": "brand",            # 品牌
    "Size": "size",              # 尺码
}


def classify_clothing(
    image_url: str | None = None,
    image_base64: str | None = None,
) -> Dict[str, Any]:
    """调用 ClassifyClothing 识别服饰属性，返回规范化后的 dict。

    返回字段：type / sub_type / main_color / pattern / season / thickness /
    style_tags / brand / size / confidence / notes，
    可直接交给 clothing.py 的 _normalize_recognition 进行二次规范化。
    """
    _ensure_credentials()

    params: Dict[str, Any] = {}
    if image_url:
        params["ImageURL"] = image_url
    elif image_base64:
        params["ImageBody"] = image_base64
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少图片源")

    payload = _call("ClassifyClothingRequest", params)
    data = payload.get("Data") or payload.get("data") or {}

    # 阿里云返回的属性是一个数组 [{Label: "...", Value: "...", Score: 0.xx}]
    attributes = data.get("Attributes") or data.get("attributes") or []
    # 有时候也会直接返回扁平的 Category / Color 等字段
    flat: Dict[str, str] = {k: str(v) for k, v in data.items() if isinstance(v, (str, int, float))}

    if isinstance(attributes, list):
        for item in attributes:
            if not isinstance(item, dict):
                continue
            label = str(item.get("Label") or item.get("label") or "").strip()
            value = str(item.get("Value") or item.get("value") or "").strip()
            if label and value:
                flat[label] = value

    logger.info("viapi ClassifyClothing flat=%s", json.dumps(flat, ensure_ascii=False))

    result: Dict[str, Any] = {}
    for label, value in flat.items():
        internal = _CLOTHING_FIELD_MAP.get(label) or _CLOTHING_FIELD_MAP.get(label.capitalize())
        if internal:
            # 兼容：阿里云可能同时返回 "Category: 上衣" 与 "CategorySub: T恤"
            if internal in {"type", "sub_type"} and value:
                # 优先保留已有值，否则覆盖
                result[internal] = result.get(internal) or value
            elif internal == "season":
                existing = result.get("season") or ""
                result["season"] = f"{existing},{value}".strip(",") if existing else value
            elif internal == "style_tags":
                existing = result.get("style_tags") or ""
                result["style_tags"] = f"{existing},{value}".strip(",") if existing else value
            else:
                result[internal] = result.get(internal) or value

    # confidence：取 Score 的平均值作为粗略置信度
    scores = []
    if isinstance(attributes, list):
        for item in attributes:
            if isinstance(item, dict):
                try:
                    scores.append(float(item.get("Score") or item.get("score") or 0))
                except (TypeError, ValueError):
                    pass
    if scores:
        result["confidence"] = round(sum(scores) / len(scores), 2)
    else:
        result["confidence"] = 0.75

    # 补充一个简短说明，便于前端展示
    result["notes"] = "来自阿里云视觉智能：类别/颜色/厚度 等字段仅供参考，请结合实物人工确认。"
    return result
