from __future__ import annotations

from app.v2.integrations.recognition import ChatRecognitionProvider


class ArkProvider(ChatRecognitionProvider):
    """ArkProvider(api_key, model, base_url, http_client=None).

    Configure the frozen model/endpoint ID and regional API base URL explicitly;
    e.g. https://ark.cn-beijing.volces.com/api/v3. No SDK or hidden retry loop.
    """

    provider_name = 'ark'

    def extra_payload(self):
        return {'thinking': {'type': 'disabled'}}
