from __future__ import annotations

from app.v2.integrations.recognition import ChatRecognitionProvider


class QwenProvider(ChatRecognitionProvider):
    """QwenProvider(api_key, model, base_url, http_client=None).

    Configure the model and regional OpenAI-compatible base URL explicitly;
    e.g. https://<workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1.
    """

    provider_name = 'qwen'

    def extra_payload(self):
        return {'enable_thinking': False}
