from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    wechat_appid: str = ""
    wechat_secret: str = ""
    dev_wechat_mock: bool = False
    debug: bool = False
    cors_origins: str = "*"
    upload_backend: str = "local"
    upload_dir: str = "uploads"
    public_base_url: str = "http://127.0.0.1:8000"
    tencent_cos_secret_id: str = ""
    tencent_cos_secret_key: str = ""
    tencent_cos_region: str = ""
    tencent_cos_bucket: str = ""
    tencent_cos_prefix: str = "zhida-kids/dev"
    tencent_cos_public_base_url: str = ""
    ai_image_data_url_fallback: bool = False
    qweather_api_key: str = ""
    ark_api_key: str = ""
    ark_responses_url: str = "https://ark.cn-beijing.volces.com/api/v3/responses"
    ark_clothing_model: str = "doubao-seed-2-0-mini-260215"
    gptsapi_api_key: str = ""
    gptsapi_base_url: str = "https://api.gptsapi.net/v1/messages"
    gptsapi_model: str = "claude-sonnet-4-6"
    gptsapi_image_edit_url: str = "https://api.gptsapi.net/api/v3/openai/gpt-image-2-plus/image-edit"
    gptsapi_image_output_format: str = "png"
    gptsapi_image_poll_interval: int = 2
    gptsapi_image_poll_max_attempts: int = 30
    dev_ai_mock: bool = False
    dev_outfit_mock: bool = False
    style_ruleset_path: str = "app/style_profiles/kids_outfit_cn_v1.yaml"
    style_ruleset_id: str = "kids_outfit_cn_v1"
    # 阿里云视觉智能开放平台（用于服饰抠图 + 服饰属性识别）
    # 默认值留空，通过环境变量 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET 注入
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_viapi_region: str = "cn-shanghai"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
