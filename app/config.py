"""应用配置 - 通过 pydantic-settings 加载 .env"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== App =====
    app_name: str = "二掌柜订舱系统"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    secret_key: str = "change-me-in-production-please-32-chars-min"

    # ===== Database =====
    database_url: str = "sqlite+aiosqlite:///./data/freight.db"

    # ===== Upload =====
    upload_dir: Path = Path("./uploads")
    max_upload_size_mb: int = 20

    # ===== OCR =====
    paddleocr_lang: str = "ch"
    paddleocr_use_gpu: bool = False
    paddleocr_use_angle_cls: bool = True
    paddleocr_model_dir: str = ""

    # ===== Email / SMTP =====
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    smtp_from_name: str = "二掌柜订舱"
    smtp_from_email: str = "ops@example.com"

    # ===== Scheduled tasks =====
    email_poll_cron: str = ""

    # ===== Carrier templates =====
    carrier_templates_path: Path = Path("./app/data/carrier_templates.json")

    @property
    def upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # 运行时确保目录存在
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    (s.upload_dir / "so").mkdir(parents=True, exist_ok=True)
    (s.upload_dir / "bills").mkdir(parents=True, exist_ok=True)
    (s.upload_dir / "attachments").mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
