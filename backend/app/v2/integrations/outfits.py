"""Bounded text-only ranking of server-approved combinations."""
import json
import httpx


class OutfitProvider:
    def __init__(self, settings, http_client=None):
        self.settings, self.http_client = settings, http_client

    def recommend(self, payload):
        settings = self.settings
        if settings.outfit_provider == 'disabled':
            return None
        key = settings.qwen_api_key if settings.outfit_provider == 'qwen' else settings.ark_api_key
        base = settings.qwen_base_url if settings.outfit_provider == 'qwen' else settings.ark_base_url
        if not key.get_secret_value():
            return None
        # Only categorical garment attributes and approved combinations go to the model.
        safe = {'scene': payload['scene'], 'styles': payload['styles'],
                'combinations': [[{k: i.get(k) for k in ('garment_id', 'category', 'colors', 'pattern', 'thickness')}
                                  for i in combo] for combo in payload['combinations'][:20]]}
        body = {'model': settings.outfit_model, 'messages': [
            {'role': 'system', 'content': 'Choose one supplied clothing combination. Return JSON with garment_ids and a concise Chinese reason. Never invent items.'},
            {'role': 'user', 'content': json.dumps(safe, ensure_ascii=False)}],
                'temperature': 0.2, 'max_tokens': 500}
        if settings.outfit_provider == 'qwen':
            body['enable_thinking'] = False
        client = self.http_client or httpx
        response = client.post(base.rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key.get_secret_value()}, json=body,
            timeout=settings.outfit_timeout_seconds)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        return json.loads(content)
