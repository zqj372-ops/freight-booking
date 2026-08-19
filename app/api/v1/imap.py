"""IMAP 拉取 API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.email_ingestion import (
    EmailIngestion,
    IngestionSource,
    ProcessedEmail,
)
from app.schemas.email_ingestion import (
    EmailIngestionRead,
    IngestionResultRead,
    ProcessedEmailRead,
)
from app.services.imap_service import run_ingestion

router = APIRouter()


@router.post("/ingest-now", response_model=IngestionResultRead)
async def ingest_now(
    source: IngestionSource | None = Query(None, description="强制 mock/IMAP, 留空自动判断"),
    db: AsyncSession = Depends(db_session),
) -> IngestionResultRead:
    """手动触发一次拉取"""
    result = await run_ingestion(db, source=source)
    return IngestionResultRead(
        ingestion_id=result.ingestion_id,
        source=result.source,
        total_fetched=result.total_fetched,
        new_count=result.new_count,
        skip_count=result.skip_count,
        error_count=result.error_count,
        error=result.error,
        so_ids=result.so_ids,
    )


@router.get("/ingestions", response_model=list[EmailIngestionRead])
async def list_ingestions(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> list[EmailIngestionRead]:
    """列出历次拉取会话"""
    stmt = select(EmailIngestion).order_by(EmailIngestion.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(EmailIngestion.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [EmailIngestionRead.model_validate(r) for r in rows]


@router.get("/ingestions/{ingestion_id}", response_model=EmailIngestionRead)
async def get_ingestion(
    ingestion_id: str,
    db: AsyncSession = Depends(db_session),
) -> EmailIngestionRead:
    ing = (
        await db.execute(select(EmailIngestion).where(EmailIngestion.id == ingestion_id))
    ).scalar_one_or_none()
    if not ing:
        raise HTTPException(status_code=404, detail="ingestion not found")
    return EmailIngestionRead.model_validate(ing)


@router.get("/processed", response_model=list[ProcessedEmailRead])
async def list_processed(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(db_session),
) -> list[ProcessedEmailRead]:
    """列出已处理的邮件 (去重记录)"""
    stmt = select(ProcessedEmail).order_by(ProcessedEmail.processed_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ProcessedEmailRead.model_validate(r) for r in rows]
