"""v0.6.2 清单复核 API

5 个 endpoint:
- POST  /shipments/{id}/checklist-reviews        启动复核 (自动跑 4 大类规则)
- GET   /shipments/{id}/checklist-reviews        复核历史列表
- GET   /checklist-reviews/{id}                  单次复核详情 (含 items)
- POST  /checklist-reviews/{id}/items/{iid}/ack  确认某复核项 (warning 强制 pass)
- POST  /checklist-reviews/{id}/signoff          签收整个复核
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.core.audit import Actor, write_audit_log
from app.core.organization_context import get_default_organization
from app.models._base import AuditAction
from app.models.checklist import (
    ChecklistItem,
    ChecklistReview,
    ChecklistReviewStatus,
    ChecklistReviewType,
)
from app.models.shipment import Shipment
from app.schemas.checklist import (
    ChecklistAcknowledgeRequest,
    ChecklistItemRead,
    ChecklistReviewCreate,
    ChecklistReviewListItem,
    ChecklistReviewRead,
    ChecklistSignoffRequest,
)
from app.services import checklist as checklist_service

router = APIRouter()


# ========== 1. POST /shipments/{id}/checklist-reviews (启动) ==========


@router.post(
    "/shipments/{shipment_id}/checklist-reviews",
    response_model=ChecklistReviewRead,
    status_code=201,
)
async def start_checklist(
    shipment_id: str,
    payload: ChecklistReviewCreate,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ChecklistReviewRead:
    """启动一次清单复核 (跑完 4 大类规则)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    s = (
        await db.execute(
            select(Shipment).where(
                Shipment.id == shipment_id,
                Shipment.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    review = await checklist_service.start_checklist(
        db,
        s,
        review_type=ChecklistReviewType(payload.review_type),
        trigger_reason=payload.trigger_reason,
        user_id=actor.user_id if hasattr(actor, "user_id") else None,
        user_name=actor.name if hasattr(actor, "name") else None,
        note=payload.note,
    )
    await db.commit()
    await db.refresh(review)

    # audit
    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="checklist_review",
        entity_id=review.id,
        action=AuditAction.CREATE,
        actor=actor,
        field_changes={
            "review_type": payload.review_type,
            "total_items": review.total_items,
            "critical": review.critical_items,
            "warning": review.warning_items,
        },
    )
    await db.commit()

    # 返完整 review + items
    return await _build_review_read(db, review.id)


# ========== 2. GET /shipments/{id}/checklist-reviews (历史) ==========


@router.get(
    "/shipments/{shipment_id}/checklist-reviews",
    response_model=list[ChecklistReviewListItem],
)
async def list_reviews(
    shipment_id: str,
    status: str | None = Query(None, description="draft/completed/signed_off/auto_closed"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(db_session),
) -> list[ChecklistReviewListItem]:
    org = await get_default_organization(db)
    s = (
        await db.execute(
            select(Shipment).where(
                Shipment.id == shipment_id,
                Shipment.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="shipment not found")

    s_enum = None
    if status:
        try:
            s_enum = ChecklistReviewStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")

    reviews = await checklist_service.list_reviews(
        db, shipment_id, status=s_enum, limit=limit,
    )
    return [ChecklistReviewListItem.model_validate(r) for r in reviews]


# ========== 3. GET /checklist-reviews/{id} (详情) ==========


@router.get(
    "/checklist-reviews/{review_id}",
    response_model=ChecklistReviewRead,
)
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(db_session),
) -> ChecklistReviewRead:
    org = await get_default_organization(db)
    return await _build_review_read(db, review_id, org_id=org.id)


# ========== 4. POST /checklist-reviews/{id}/items/{iid}/ack ==========


@router.post(
    "/checklist-reviews/{review_id}/items/{item_id}/ack",
    response_model=ChecklistItemRead,
)
async def acknowledge_item(
    review_id: str,
    item_id: str,
    payload: ChecklistAcknowledgeRequest,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ChecklistItemRead:
    """操作员确认某复核项 (warning 强制 pass)"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    item = (
        await db.execute(
            select(ChecklistItem).where(
                ChecklistItem.id == item_id,
                ChecklistItem.review_id == review_id,
                ChecklistItem.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="checklist item not found")

    user_id = actor.user_id if hasattr(actor, "user_id") else "anonymous"
    await checklist_service.acknowledge_item(db, item, user_id, note=payload.note)
    await db.commit()
    await db.refresh(item)

    return ChecklistItemRead.model_validate(item)


# ========== 5. POST /checklist-reviews/{id}/signoff ==========


@router.post(
    "/checklist-reviews/{review_id}/signoff",
    response_model=ChecklistReviewRead,
)
async def signoff(
    review_id: str,
    payload: ChecklistSignoffRequest,
    request: Request,
    db: AsyncSession = Depends(db_session),
) -> ChecklistReviewRead:
    """签收整个复核"""
    org = await get_default_organization(db)
    actor = Actor.from_request(request)

    review = (
        await db.execute(
            select(ChecklistReview).where(
                ChecklistReview.id == review_id,
                ChecklistReview.organization_id == org.id,
            )
        )
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="checklist review not found")
    if review.status == ChecklistReviewStatus.SIGNED_OFF:
        raise HTTPException(status_code=400, detail="already signed off")

    user_id = actor.user_id if hasattr(actor, "user_id") else "anonymous"
    user_name = actor.name if hasattr(actor, "name") else "anonymous"
    await checklist_service.signoff_review(db, review, user_id, user_name, note=payload.note)
    await db.commit()
    await db.refresh(review)

    await write_audit_log(
        db,
        organization_id=org.id,
        entity_type="checklist_review",
        entity_id=review.id,
        action=AuditAction.UPDATE,
        actor=actor,
        field_changes={
            "status": ChecklistReviewStatus.SIGNED_OFF.value,
            "note": payload.note,
        },
    )
    await db.commit()

    return await _build_review_read(db, review.id, org_id=org.id)


# ========== 辅助 ==========


async def _build_review_read(
    db: AsyncSession,
    review_id: str,
    org_id: str | None = None,
) -> ChecklistReviewRead:
    review = (
        await db.execute(
            select(ChecklistReview).where(ChecklistReview.id == review_id)
        )
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="checklist review not found")
    if org_id and review.organization_id != org_id:
        raise HTTPException(status_code=404, detail="checklist review not found")

    items = (
        await db.execute(
            select(ChecklistItem)
            .where(ChecklistItem.review_id == review_id)
            .order_by(ChecklistItem.created_at.asc())
        )
    ).scalars().all()

    return ChecklistReviewRead(
        id=review.id,
        shipment_id=review.shipment_id,
        review_type=review.review_type.value,
        status=review.status.value,
        reviewed_at=review.reviewed_at,
        signed_off_at=review.signed_off_at,
        reviewed_by_user_id=review.reviewed_by_user_id,
        reviewed_by_user_name=review.reviewed_by_user_name,
        total_items=review.total_items,
        passed_items=review.passed_items,
        warning_items=review.warning_items,
        critical_items=review.critical_items,
        overall_severity=review.overall_severity.value,
        trigger_reason=review.trigger_reason,
        related_exception_ids=review.related_exception_ids,
        note=review.note,
        items=[ChecklistItemRead.model_validate(i) for i in items],
        created_at=review.created_at,
    )
