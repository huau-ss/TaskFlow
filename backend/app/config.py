from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://taskflow:taskflow@localhost:5432/taskflow"
    database_url_sync: str = "postgresql://taskflow:taskflow@localhost:5432/taskflow"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ── FunASR 统一语音服务（替换旧的 ASR+声纹分离+pipeline）──
    funasr_url: str = "http://localhost:8005"

    # ── DEPRECATED: 以下旧服务配置，FunASR 上线后移除 ──
    asr_url: str = "http://192.168.10.11:8001"
    asr_diarize_url: str = "http://192.168.10.11:8002/api/transcribe"
    embedding_url: str = "http://localhost:8003"
    diarization_url: str = "http://localhost:8004"

    llm_url: str = "http://192.168.10.11:8080/v1"
    llm_model: str = "qwen2.5-72b-instruct"
    llm_api_key: str = "not-needed"

    nas_path: str = "./data/nas/meetings"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "*"
    mock_asr: bool = False

    # Email settings
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = "notifications@example.com"
    smtp_password: str = ""
    smtp_from_name: str = "TaskFlow System"
    smtp_use_tls: bool = True
    email_base_url: str = "http://192.168.10.8/api/tasks"

    # Task notification settings
    reminder_before_hours: int = 24  # 截止前多少小时发送提醒


settings = Settings()
