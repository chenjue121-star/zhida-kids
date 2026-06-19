import json
from typing import Any


def _compact_ark_request(request_body: dict[str, Any]) -> dict[str, Any]:
    compact = json.loads(json.dumps(request_body, ensure_ascii=False))
    for item in compact.get("input") or []:
        for block in item.get("content") or []:
            image_url = block.get("image_url")
            if isinstance(image_url, str) and image_url.startswith("data:"):
                header = image_url.split(",", 1)[0]
                block["image_url"] = f"{header},<base64 {len(image_url)} chars>"
            text = block.get("text")
            if isinstance(text, str) and len(text) > 3000:
                block["text"] = f"{text[:3000]}..."
    return compact
