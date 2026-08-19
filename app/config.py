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

    # ===== IMAP =====
    imap_enabled: bool = False
    imap_host: str = "imap.exmail.qq.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_mailbox: str = "INBOX"
    imap_filter_from: str = ""  # 白名单发件人,逗号分隔,空=不过滤
    imap_filter_subject_keywords: str = "SO,Booking,订舱,BL,提单"
    # 关键词命中才拉,逗号分隔,大小写不敏感
    imap_poll_interval_seconds: int = 300  # 5 分钟
    imap_max_per_poll: int = 50  # 单次最多拉 N 封
    imap_mock_mode: bool = True  # 没配凭据自动 true
    imap_mock_dir: Path = Path("./samples/imap")

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
