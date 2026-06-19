import json
import logging
from typing import Any, Union

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Union[dict, list]:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 未返回识别结果")

    # 去除 markdown code fence
    lines = cleaned.splitlines()
    if lines and lines[0].strip().startswith("```"):
        stripped_lines = []
        in_fence = False
        fence_start_seen = False
        for line in lines:
            if line.strip().startswith("```"):
                if not fence_start_seen:
                    in_fence = True
                    fence_start_seen = True
                else:
                    in_fence = False
                continue
            if fence_start_seen and not in_fence:
                break
            if fence_start_seen or not line.strip().startswith("```"):
                stripped_lines.append(line)
        cleaned = "\n".join(stripped_lines).strip()

    # 查找第一个 { 或 [
    obj_start = cleaned.find("{")
    arr_start = cleaned.find("[")
    start_idx = -1
    if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
        start_idx = obj_start
        end_marker = "}"
    elif arr_start >= 0:
        start_idx = arr_start
        end_marker = "]"
    else:
        logger.warning("AI 识别结果不含 JSON: raw_text=%r", text[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON")

    # 从 start_idx 开始搜索匹配的右括号
    depth = 0
    in_string = False
    escape_next = False
    end_idx = -1
    for i in range(start_idx, len(cleaned)):
        ch = cleaned[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{" or ch == "[":
            depth += 1
        elif ch == "}" or ch == "]":
            depth -= 1
            if depth == 0 and (end_marker == ch or (end_marker == "}" and ch == "}") or (end_marker == "]" and ch == "]")):
                end_idx = i + 1
                break
    if end_idx <= start_idx:
        logger.warning("AI 识别 JSON 括号不匹配: raw_text=%r", text[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON")

    candidate = cleaned[start_idx:end_idx]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("AI JSON parse failed: error=%s candidate=%r", str(exc), candidate[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是合法 JSON") from exc

def _extract_ark_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, str):
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        if not isinstance(value, dict):
            return

        out_text = value.get("output_text")
        if isinstance(out_text, str) and out_text and out_text not in texts:
            texts.append(out_text)

        for text_key in ("text", "content", "message"):
            v = value.get(text_key)
            if isinstance(v, str) and v and v not in texts:
                texts.append(v)

        for nested_key in ("output", "data", "choices", "candidates"):
            if nested_key in value:
                walk(value[nested_key], depth + 1)

        # 兼容 openai-style: choices -> message -> content
        choices = value.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    msg = choice.get("message") or choice.get("delta")
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str) and content and content not in texts:
                            texts.append(content)

    walk(data)
    combined = "\n".join(t for t in texts if t).strip()
    if combined:
        return combined

    # 终极兜底：如果没找到结构化的文本字段，尝试对整个响应做 json.dumps 后搜索
    try:
        raw = json.dumps(data, ensure_ascii=False)
        if len(raw) > 300:
            return ""
    except Exception:
        return ""
    return ""

def _pick_recognition_object(parsed: Union[dict, list]) -> dict:
    if isinstance(parsed, dict):
        if "type" in parsed or "main_color" in parsed or "category" in parsed:
            return parsed
        # 对象是包裹的，从常见 key 中搜索
        for key in ("result", "data", "item", "item_info", "clothing", "recognition"):
            value = parsed.get(key)
            if isinstance(value, dict):
                return _pick_recognition_object(value)
        return parsed

    if not isinstance(parsed, list):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果不是对象")

    candidates = [item for item in parsed if isinstance(item, dict)]
    if not candidates:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 识别结果为空")

    def score_candidate(c: dict) -> float:
        s = 0.0
        for key in ("type", "category", "main_color", "color", "categoryPrimary"):
            if c.get(key):
                s += 1.0
        try:
            s += float(c.get("confidence") or 0) * 2
        except (TypeError, ValueError):
            pass
        return s

    selected = max(candidates, key=score_candidate)
    note = "识别到多件衣物，已优先选择信息最完整的一件，请确认或手动调整。"
    existing_notes = selected.get("notes") or ""
    selected["notes"] = f"{note} {existing_notes}".strip()
    return selected
