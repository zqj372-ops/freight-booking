"""公用 Mixin"""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """created_at / updated_at

    关键: 用 Python 端 datetime.now() 而非 server_default=func.now()
    - server_default 用数据库 CURRENT_TIMESTAMP, SQLite 是秒级, 同秒多条记录
      ORDER BY created_at DESC 不稳定 (回退到 rowid ASC, 最早插入的排第一)
    - Python 端 datetime.now(timezone.utc) 带微妙精度, 同事务内多条记录也有序
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
