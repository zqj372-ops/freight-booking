"""API 依赖项"""

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for s in get_db():
        yield s


DbSession = Depends(db_session)
