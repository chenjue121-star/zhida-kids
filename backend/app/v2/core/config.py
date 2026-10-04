from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class V2Settings(BaseSettings):
    database_url: str
    jwt_secret: SecretStr
    env: Literal['development', 'test', 'production'] = 'development'
    dev_wechat_mock: bool = False
    wechat_appid: str = ''
    wechat_secret: SecretStr = SecretStr('')
    qweather_api_host: str = ''
    qweather_api_key: SecretStr = SecretStr('')
    private_storage_dir: str = str(BACKEND_ROOT / 'var' / 'private-media')
    upload_max_bytes: int = 12 * 1024 * 1024
    recognition_provider: Literal['qwen', 'ark', 'disabled'] = 'qwen'
    recognition_model: str = 'qwen3.7-plus-2026-05-26'
    qwen_api_key: SecretStr = SecretStr('')
    qwen_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    ark_api_key: SecretStr = SecretStr('')
    ark_base_url: str = 'https://ark.cn-beijing.volces.com/api/v3'
    recognition_max_attempts: int = 3
    recognition_lease_seconds: int = 120
    outfit_provider: Literal['qwen', 'ark', 'disabled'] = 'disabled'
    outfit_model: str = 'qwen3.7-plus-2026-05-26'
    outfit_timeout_seconds: int = 15
    jwt_issuer: str = 'zhida-v2'
    jwt_audience: str = 'zhida-miniprogram-v2'
    jwt_ttl_seconds: int = 604800
    model_config = SettingsConfigDict(
        env_prefix='V2_', env_file=str(BACKEND_ROOT / '.env.v2'), extra='ignore'
    )

    @model_validator(mode='after')
    def validate_settings(self):
        if not self.database_url.strip() or not self.jwt_secret.get_secret_value().strip():
            raise ValueError('V2_DATABASE_URL and V2_JWT_SECRET must not be empty')
        if self.env == 'production' and self.dev_wechat_mock:
            raise ValueError('Wechat mock is forbidden in production')
        if self.jwt_ttl_seconds <= 0:
            raise ValueError('JWT lifetime must be positive')
        if self.upload_max_bytes <= 0 or self.recognition_max_attempts not in range(1, 6) or self.recognition_lease_seconds < 30:
            raise ValueError('Invalid media/recognition limits')
        if not 1 <= self.outfit_timeout_seconds <= 60:
            raise ValueError('Invalid outfit timeout')
        if not Path(self.private_storage_dir).is_absolute():
            raise ValueError('Private storage path must be absolute')
        for value in (self.qwen_base_url, self.ark_base_url):
            if not value.startswith('https://'):
                raise ValueError('Recognition API base URLs must use HTTPS')
        if self.qweather_api_host and (not self.qweather_api_host.startswith('https://') or '/' in self.qweather_api_host[8:].strip('/')):
            raise ValueError('V2_QWEATHER_API_HOST must be an HTTPS host')
        return self
