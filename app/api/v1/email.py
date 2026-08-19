"""Email - 邮件模板 + 发送历史"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.models.email_log import EmailLog
from app.models.email_template import EmailTemplate
from app.schemas.email import (
    EmailLogRead,
    EmailSendRequest,
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateUpdate,
)
from app.services.email_service import send_email, EmailMessage, render_template

router = APIRouter()


# ===== EmailTemplate =====


@router.get("/templates", response_model=list[EmailTemplateRead])
async def list_templates(
    is_active: bool | None = None,
    db: AsyncSession = Depends(db_session),
) -> list[EmailTemplateRead]:
    stmt = select(EmailTemplate)
    if is_active is not None:
        stmt = stmt.where(EmailTemplate.is_active == is_active)
    stmt = stmt.order_by(EmailTemplate.code.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [EmailTemplateRead.model_validate(r) for r in rows]


@router.post("/templates", response_model=EmailTemplateRead, status_code=201)
async def create_template(
    payload: EmailTemplateCreate,
    db: AsyncSession = Depends(db_session),
) -> EmailTemplateRead:
    t = EmailTemplate(**payload.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return EmailTemplateRead.model_validate(t)


@router.get("/templates/{tid}", response_model=EmailTemplateRead)
async def get_template(tid: str, db: AsyncSession = Depends(db_session)) -> EmailTemplateRead:
    t = (await db.execute(select(EmailTemplate).where(EmailTemplate.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="template not found")
    return EmailTemplateRead.model_validate(t)


@router.patch("/templates/{tid}", response_model=EmailTemplateRead)
async def update_template(
    tid: str,
    payload: EmailTemplateUpdate,
    db: AsyncSession = Depends(db_session),
) -> EmailTemplateRead:
    t = (await db.execute(select(EmailTemplate).where(EmailTemplate.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="template not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    return EmailTemplateRead.model_validate(t)


@router.delete("/templates/{tid}", status_code=204)
async def delete_template(tid: str, db: AsyncSession = Depends(db_session)) -> None:
    t = (await db.execute(select(EmailTemplate).where(EmailTemplate.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="template not found")
    await db.delete(t)
    await db.commit()


@router.post("/templates/{tid}/preview")
async def preview_template(
    tid: str,
    context: dict,
    db: AsyncSession = Depends(db_session),
) -> dict:
    """预览渲染结果, 不发送"""
    t = (await db.execute(select(EmailTemplate).where(EmailTemplate.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="template not found")
    s, b = render_template(t.subject, t.body, context)
    return {"subject": s, "body": b}


# ===== EmailLog =====


@router.get("/logs", response_model=list[EmailLogRead])
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    booking_id: str | None = None,
    db: AsyncSession = Depends(db_session),
) -> list[EmailLogRead]:
    stmt = select(EmailLog)
    if status:
        stmt = stmt.where(EmailLog.status == status)
    if booking_id:
        stmt = stmt.where(EmailLog.booking_id == booking_id)
    stmt = stmt.order_by(EmailLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return [EmailLogRead.model_validate(r) for r in rows]


@router.post("/send", response_model=EmailLogRead, status_code=201)
async def send_email_now(
    payload: EmailSendRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(db_session),
) -> EmailLogRead:
    """手动发邮件, 异步执行"""
    msg = EmailMessage(
        to_emails=payload.to_emails,
        cc_emails=payload.cc_emails,
        subject=payload.subject,
        body=payload.body,
        attachments=payload.attachments,
        template_code=payload.template_code,
        booking_id=payload.booking_id,
        so_id=payload.so_id,
        context=payload.context,
    )

    # 走后台任务避免阻塞
    async def _do() -> None:
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            try:
                await send_email(msg, session)
            except Exception as e:
                from loguru import logger

                logger.exception("手动发邮件失败: {}", e)

    background_tasks.add_task(_do)

    # 立即返回 pending log
    log = EmailLog(
        template_code=payload.template_code,
        to_emails=payload.to_emails,
        cc_emails=payload.cc_emails,
        subject=payload.subject,
        body=payload.body,
        attachments=payload.attachments,
        booking_id=payload.booking_id,
        so_id=payload.so_id,
        context=payload.context,
        status="pending",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return EmailLogRead.model_validate(log)
