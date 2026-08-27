"""v0.6.2 清单复核 service

4 大类 14 项核对规则:
- CONTAINER (3 项): container_no_missing / seal_no_missing / container_type_mismatch / container_count_mismatch
- DECLARATION (3 项): pieces_mismatch / weight_mismatch / volume_mismatch
- HS_CODE (3 项): hs_code_mismatch / dangerous_goods_flag_missing / oversize_goods_flag_missing
- CUTOFF_DOC (4 项): si_missing / vgm_missing / ci_missing / pl_missing

跑流程:
1. start_checklist(db, shipment_id, review_type) → 自动跑完 14 项 → ChecklistReview + 14 ChecklistItem
2. critical/warning 项自动建 OperationalException (打通 v0.6.1 AI 跟进)
3. 操作员 acknowledge (warning 强制 pass) / signoff

阈值 (可调):
- 数量字段: 差异 <=5% 警告, >5% 严重
- 重量字段: 差异 <=2% 警告, >2% 严重
- 体积字段: 差异 <=3% 警告, >3% 严重
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import (
    ChecklistItem,
    ChecklistItemCategory,
    ChecklistItemCode,
    ChecklistReview,
    ChecklistReviewStatus,
    ChecklistReviewType,
    ChecklistSeverity,
)
from app.models.container import Container
from app.models.document import Document, DocumentExtraction, DocumentType
from app.models.operational_exception import (
    ExceptionCode,
    ExceptionDetectedBy,
    ExceptionSeverity,
    ExceptionStatus,
    OperationalException,
)
from app.models.shipment import Shipment

# 阈值 (差值百分比)
_PIECES_THRESHOLD_WARN = 5.0
_PIECES_THRESHOLD_CRIT = 10.0
_WEIGHT_THRESHOLD_WARN = 2.0
_WEIGHT_THRESHOLD_CRIT = 5.0
_VOLUME_THRESHOLD_WARN = 3.0
_VOLUME_THRESHOLD_CRIT = 8.0


# ========== 单项核对规则 ==========


def _make_pass_item(
    code: ChecklistItemCode,
    category: ChecklistItemCategory,
    label: str,
    expected: str,
    actual: str,
    related_container_id: str | None = None,
    related_document_id: str | None = None,
) -> dict[str, Any]:
    """构造一个 pass 项的 dict (供 service 批量 insert)"""
    return {
        "id": str(uuid.uuid4()),
        "code": code,
        "category": category,
        "label": label,
        "expected_value": expected,
        "actual_value": actual,
        "match": True,
        "severity": ChecklistSeverity.PASS,
        "delta": None,
        "delta_pct": None,
        "related_document_id": related_document_id,
        "related_container_id": related_container_id,
    }


def _make_fail_item(
    code: ChecklistItemCode,
    category: ChecklistItemCategory,
    label: str,
    expected: str,
    actual: str,
    severity: ChecklistSeverity,
    delta: float | None = None,
    delta_pct: float | None = None,
    related_container_id: str | None = None,
    related_document_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "code": code,
        "category": category,
        "label": label,
        "expected_value": expected,
        "actual_value": actual,
        "match": False,
        "severity": severity,
        "delta": delta,
        "delta_pct": delta_pct,
        "related_document_id": related_document_id,
        "related_container_id": related_container_id,
    }


def _pct_diff(expected: float, actual: float) -> float:
    """差值百分比 (|actual - expected| / max(expected, 1) * 100)"""
    if expected == 0:
        return 100.0 if actual != 0 else 0.0
    return abs(actual - expected) / expected * 100


# ========== 4 大类规则 ==========


async def _check_container(
    db: AsyncSession, shipment: Shipment
) -> list[dict[str, Any]]:
    """CONTAINER 类别: 柜号/封条/柜型/柜数

    返回 3-4 个 item (1 + N 柜)
    """
    items: list[dict[str, Any]] = []
    containers = (
        await db.execute(
            select(Container).where(Container.shipment_id == shipment.id)
        )
    ).scalars().all()

    # 1. 柜数核对
    expected_count = shipment.container_count or 0
    actual_count = len(containers)
    if expected_count == actual_count:
        items.append(_make_pass_item(
            ChecklistItemCode.CONTAINER_COUNT_MISMATCH,
            ChecklistItemCategory.CONTAINER,
            "柜数一致性",
            f"{expected_count} 个",
            f"{actual_count} 个",
        ))
    else:
        delta = abs(actual_count - expected_count)
        severity = (
            ChecklistSeverity.CRITICAL
            if actual_count == 0 or expected_count == 0
            else ChecklistSeverity.WARNING
        )
        items.append(_make_fail_item(
            ChecklistItemCode.CONTAINER_COUNT_MISMATCH,
            ChecklistItemCategory.CONTAINER,
            "柜数一致性",
            f"{expected_count} 个",
            f"{actual_count} 个",
            severity,
            delta=float(delta),
            delta_pct=_pct_diff(expected_count, actual_count),
        ))

    # 2. 每个柜的柜号/封条/柜型
    for c in containers:
        # 柜号
        if c.container_no:
            items.append(_make_pass_item(
                ChecklistItemCode.CONTAINER_NO_MISSING,
                ChecklistItemCategory.CONTAINER,
                f"柜号 ({c.id[:8]})",
                c.container_no,
                c.container_no,
                related_container_id=c.id,
            ))
        else:
            items.append(_make_fail_item(
                ChecklistItemCode.CONTAINER_NO_MISSING,
                ChecklistItemCategory.CONTAINER,
                f"柜号 ({c.id[:8]})",
                "必填",
                "(空)",
                ChecklistSeverity.CRITICAL,
                related_container_id=c.id,
            ))
        # 封条
        if c.seal_no:
            items.append(_make_pass_item(
                ChecklistItemCode.SEAL_NO_MISSING,
                ChecklistItemCategory.CONTAINER,
                f"封条 ({c.container_no or c.id[:8]})",
                c.seal_no,
                c.seal_no,
                related_container_id=c.id,
            ))
        else:
            items.append(_make_fail_item(
                ChecklistItemCode.SEAL_NO_MISSING,
                ChecklistItemCategory.CONTAINER,
                f"封条 ({c.container_no or c.id[:8]})",
                "必填",
                "(空)",
                ChecklistSeverity.CRITICAL,
                related_container_id=c.id,
            ))
        # 柜型
        # v0.5 Shipment 没有 container_type 字段 (在 Container 表里)
        # 多柜时检查柜型一致性; 单柜直接 pass
        if len(containers) <= 1:
            items.append(_make_pass_item(
                ChecklistItemCode.CONTAINER_TYPE_MISMATCH,
                ChecklistItemCategory.CONTAINER,
                f"柜型 ({c.container_no or c.id[:8]})",
                c.container_type,
                c.container_type,
                related_container_id=c.id,
            ))
        else:
            first_type = containers[0].container_type
            if c.container_type == first_type:
                items.append(_make_pass_item(
                    ChecklistItemCode.CONTAINER_TYPE_MISMATCH,
                    ChecklistItemCategory.CONTAINER,
                    f"柜型一致 ({c.container_no or c.id[:8]})",
                    first_type,
                    c.container_type,
                    related_container_id=c.id,
                ))
            else:
                items.append(_make_fail_item(
                    ChecklistItemCode.CONTAINER_TYPE_MISMATCH,
                    ChecklistItemCategory.CONTAINER,
                    f"柜型一致 ({c.container_no or c.id[:8]})",
                    first_type,
                    c.container_type,
                    ChecklistSeverity.CRITICAL,
                    related_container_id=c.id,
                ))

    return items


async def _check_declaration(
    db: AsyncSession, shipment: Shipment
) -> list[dict[str, Any]]:
    """DECLARATION 类别: 件数/重量/体积 (申报 vs 实际 packing list 提取)

    实际值来源: DocumentExtraction (PL 类型的 fields.pieces/weight_kg/volume_cbm)
    """
    items: list[dict[str, Any]] = []

    # 找最新 PL (packing list) 提取
    pl_extraction = (
        await db.execute(
            select(DocumentExtraction)
            .join(Document, Document.id == DocumentExtraction.document_id)
            .where(
                Document.shipment_id == shipment.id,
                Document.doc_type == DocumentType.PACKING_LIST,
            )
            .order_by(DocumentExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    actual_pieces = None
    actual_weight = None
    actual_volume = None
    pl_doc_id = None
    if pl_extraction:
        fields = pl_extraction.fields or {}
        actual_pieces = fields.get("pieces")
        actual_weight = fields.get("weight_kg")
        actual_volume = fields.get("volume_cbm")
        pl_doc_id = pl_extraction.document_id

    # 件数
    expected_pieces = shipment.pieces or 0
    if actual_pieces is None:
        # 没 PL 提取, skip (不报)
        items.append(_make_pass_item(
            ChecklistItemCode.PIECES_MISMATCH,
            ChecklistItemCategory.DECLARATION,
            "件数 (申报 vs PL)",
            f"{expected_pieces}",
            "无 PL 提取数据",
        ))
    else:
        pct = _pct_diff(expected_pieces, actual_pieces)
        delta = actual_pieces - expected_pieces
        if pct <= _PIECES_THRESHOLD_WARN:
            items.append(_make_pass_item(
                ChecklistItemCode.PIECES_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "件数 (申报 vs PL)",
                f"{expected_pieces}",
                f"{actual_pieces} (差 {delta:+.0f} 件, {pct:.1f}%)",
                related_document_id=pl_doc_id,
            ))
        else:
            sev = (
                ChecklistSeverity.CRITICAL
                if pct > _PIECES_THRESHOLD_CRIT
                else ChecklistSeverity.WARNING
            )
            items.append(_make_fail_item(
                ChecklistItemCode.PIECES_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "件数 (申报 vs PL)",
                f"{expected_pieces}",
                f"{actual_pieces} (差 {delta:+.0f} 件, {pct:.1f}%)",
                sev,
                delta=float(delta),
                delta_pct=pct,
                related_document_id=pl_doc_id,
            ))

    # 重量
    expected_weight = shipment.weight_kg or 0
    if actual_weight is None:
        items.append(_make_pass_item(
            ChecklistItemCode.WEIGHT_MISMATCH,
            ChecklistItemCategory.DECLARATION,
            "重量 (申报 vs PL)",
            f"{expected_weight} kg",
            "无 PL 提取数据",
        ))
    else:
        pct = _pct_diff(expected_weight, actual_weight)
        delta = actual_weight - expected_weight
        if pct <= _WEIGHT_THRESHOLD_WARN:
            items.append(_make_pass_item(
                ChecklistItemCode.WEIGHT_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "重量 (申报 vs PL)",
                f"{expected_weight} kg",
                f"{actual_weight} kg (差 {delta:+.1f} kg, {pct:.1f}%)",
                related_document_id=pl_doc_id,
            ))
        else:
            sev = (
                ChecklistSeverity.CRITICAL
                if pct > _WEIGHT_THRESHOLD_CRIT
                else ChecklistSeverity.WARNING
            )
            items.append(_make_fail_item(
                ChecklistItemCode.WEIGHT_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "重量 (申报 vs PL)",
                f"{expected_weight} kg",
                f"{actual_weight} kg (差 {delta:+.1f} kg, {pct:.1f}%)",
                sev,
                delta=delta,
                delta_pct=pct,
                related_document_id=pl_doc_id,
            ))

    # 体积
    expected_volume = shipment.volume_cbm or 0
    if actual_volume is None:
        items.append(_make_pass_item(
            ChecklistItemCode.VOLUME_MISMATCH,
            ChecklistItemCategory.DECLARATION,
                "体积 (申报 vs PL)",
                f"{expected_volume} cbm",
                "无 PL 提取数据",
        ))
    else:
        pct = _pct_diff(expected_volume, actual_volume)
        delta = actual_volume - expected_volume
        if pct <= _VOLUME_THRESHOLD_WARN:
            items.append(_make_pass_item(
                ChecklistItemCode.VOLUME_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "体积 (申报 vs PL)",
                f"{expected_volume} cbm",
                f"{actual_volume} cbm (差 {delta:+.2f} cbm, {pct:.1f}%)",
                related_document_id=pl_doc_id,
            ))
        else:
            sev = (
                ChecklistSeverity.CRITICAL
                if pct > _VOLUME_THRESHOLD_CRIT
                else ChecklistSeverity.WARNING
            )
            items.append(_make_fail_item(
                ChecklistItemCode.VOLUME_MISMATCH,
                ChecklistItemCategory.DECLARATION,
                "体积 (申报 vs PL)",
                f"{expected_volume} cbm",
                f"{actual_volume} cbm (差 {delta:+.2f} cbm, {pct:.1f}%)",
                sev,
                delta=delta,
                delta_pct=pct,
                related_document_id=pl_doc_id,
            ))

    return items


async def _check_hs_code(
    db: AsyncSession, shipment: Shipment
) -> list[dict[str, Any]]:
    """HS_CODE 类别: HS code / 危险品 / 超大件

    HS code 来源: DocumentExtraction (invoice/PL 的 fields.hs_code)
    危险品/超大件: Shipment.is_dangerous/is_oversize vs Document 标记
    """
    items: list[dict[str, Any]] = []

    # 找最新 invoice/PL 提取
    extraction = (
        await db.execute(
            select(DocumentExtraction)
            .join(Document, Document.id == DocumentExtraction.document_id)
            .where(
                Document.shipment_id == shipment.id,
                Document.doc_type.in_([DocumentType.INVOICE, DocumentType.PACKING_LIST]),
            )
            .order_by(DocumentExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    expected_hs = shipment.hs_code
    actual_hs = None
    doc_id = None
    if extraction:
        fields = extraction.fields or {}
        actual_hs = fields.get("hs_code")
        doc_id = extraction.document_id

    # HS code (空都算 pass, 因为申报可能还没填)
    if not expected_hs and not actual_hs:
        items.append(_make_pass_item(
            ChecklistItemCode.HS_CODE_MISMATCH,
            ChecklistItemCategory.HS_CODE,
            "HS code 匹配",
            "(未填)",
            "(未提取)",
        ))
    elif expected_hs == actual_hs:
        items.append(_make_pass_item(
            ChecklistItemCode.HS_CODE_MISMATCH,
            ChecklistItemCategory.HS_CODE,
            "HS code 匹配",
            expected_hs or "?",
            actual_hs or "?",
            related_document_id=doc_id,
        ))
    else:
        items.append(_make_fail_item(
            ChecklistItemCode.HS_CODE_MISMATCH,
            ChecklistItemCategory.HS_CODE,
            "HS code 匹配",
            expected_hs or "(未填)",
            actual_hs or "(未提取)",
            ChecklistSeverity.WARNING,
            related_document_id=doc_id,
        ))

    # 危险品
    items.append(_make_pass_item(
        ChecklistItemCode.DANGEROUS_GOODS_FLAG_MISSING,
        ChecklistItemCategory.HS_CODE,
        "危险品标记",
        "是" if shipment.is_dangerous else "否",
        "是" if shipment.is_dangerous else "否",
    ))

    # 超大件
    items.append(_make_pass_item(
        ChecklistItemCode.OVERSIZE_GOODS_FLAG_MISSING,
        ChecklistItemCategory.HS_CODE,
        "超大件标记",
        "是" if shipment.is_oversize else "否",
        "是" if shipment.is_oversize else "否",
    ))

    return items


async def _check_cutoff_doc(
    db: AsyncSession, shipment: Shipment
) -> list[dict[str, Any]]:
    """CUTOFF_DOC 类别: SI / VGM / CI / PL 是否已传 (Document 表查)"""
    items: list[dict[str, Any]] = []
    docs = (
        await db.execute(
            select(Document).where(Document.shipment_id == shipment.id)
        )
    ).scalars().all()
    has_type = {d.doc_type for d in docs if d.doc_type}

    for doc_type, code, label in [
        (DocumentType.SI, ChecklistItemCode.SI_MISSING, "SI 补料"),
        (DocumentType.VGM, ChecklistItemCode.VGM_MISSING, "VGM 重量验证"),
        (DocumentType.INVOICE, ChecklistItemCode.CI_MISSING, "CI 发票"),
        (DocumentType.PACKING_LIST, ChecklistItemCode.PL_MISSING, "PL 装箱单"),
    ]:
        if doc_type in has_type:
            items.append(_make_pass_item(
                code, ChecklistItemCategory.CUTOFF_DOC,
                f"{label} 已传", "已传", "已传",
            ))
        else:
            items.append(_make_fail_item(
                code, ChecklistItemCategory.CUTOFF_DOC,
                f"{label} 已传", "必传", "未传",
                ChecklistSeverity.WARNING,
            ))

    return items


# ========== 主入口 ==========


async def start_checklist(
    db: AsyncSession,
    shipment: Shipment,
    review_type: ChecklistReviewType = ChecklistReviewType.RANDOM,
    trigger_reason: str | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
    note: str | None = None,
) -> ChecklistReview:
    """启动一次复核, 跑完 4 大类规则, 写 ChecklistReview + ChecklistItem

    同时, 对 critical/warning 项自动建 OperationalException (打通 v0.6.1 AI 跟进)
    """
    now = datetime.now(timezone.utc)
    review = ChecklistReview(
        id=str(uuid.uuid4()),
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        review_type=review_type,
        status=ChecklistReviewStatus.DRAFT,
        reviewed_at=now,
        reviewed_by_user_id=user_id,
        reviewed_by_user_name=user_name,
        trigger_reason=trigger_reason,
        note=note,
        shipment_snapshot={
            "container_count": shipment.container_count,
            "pieces": shipment.pieces,
            "weight_kg": shipment.weight_kg,
            "volume_cbm": shipment.volume_cbm,
            "hs_code": shipment.hs_code,
            "is_dangerous": shipment.is_dangerous,
            "is_oversize": shipment.is_oversize,
        },
    )
    db.add(review)
    await db.flush()

    # 跑 4 大类
    all_items: list[dict[str, Any]] = []
    all_items.extend(await _check_container(db, shipment))
    all_items.extend(await _check_declaration(db, shipment))
    all_items.extend(await _check_hs_code(db, shipment))
    all_items.extend(await _check_cutoff_doc(db, shipment))

    # 写 item
    passed = 0
    warning = 0
    critical = 0
    overall = ChecklistSeverity.PASS
    related_exception_ids: list[str] = []

    for it in all_items:
        item = ChecklistItem(
            id=it["id"],
            organization_id=shipment.organization_id,
            review_id=review.id,
            code=it["code"],
            category=it["category"],
            label=it["label"],
            expected_value=it["expected_value"],
            actual_value=it["actual_value"],
            match=it["match"],
            severity=it["severity"],
            delta=it["delta"],
            delta_pct=it["delta_pct"],
            related_document_id=it["related_document_id"],
            related_container_id=it["related_container_id"],
        )
        db.add(item)

        if it["severity"] == ChecklistSeverity.PASS:
            passed += 1
        elif it["severity"] == ChecklistSeverity.WARNING:
            warning += 1
        else:
            critical += 1
            if overall != ChecklistSeverity.CRITICAL:
                overall = ChecklistSeverity.CRITICAL

        # critical 自动建 OperationalException (打通 AI 跟进)
        if it["severity"] == ChecklistSeverity.CRITICAL:
            ex = await _create_exception_for_item(
                db, shipment, review, item, it,
            )
            if ex:
                related_exception_ids.append(ex.id)

    if warning > 0 and overall == ChecklistSeverity.PASS:
        overall = ChecklistSeverity.WARNING

    review.total_items = len(all_items)
    review.passed_items = passed
    review.warning_items = warning
    review.critical_items = critical
    review.overall_severity = overall
    review.related_exception_ids = related_exception_ids or None

    await db.flush()
    logger.info(
        f"shipment {shipment.id[:8]} 清单复核 {review.id[:8]} 完成: "
        f"{len(all_items)} 项 (pass={passed}, warn={warning}, crit={critical})"
    )
    return review


async def _create_exception_for_item(
    db: AsyncSession,
    shipment: Shipment,
    review: ChecklistReview,
    item: ChecklistItem,
    item_data: dict[str, Any],
) -> OperationalException | None:
    """critical 复核项 → 自动建 OperationalException"""
    # mapping item code → ExceptionCode
    code_map: dict[ChecklistItemCode, ExceptionCode] = {
        ChecklistItemCode.CONTAINER_NO_MISSING: ExceptionCode.MISSING_CONTAINER_NO,
        ChecklistItemCode.SEAL_NO_MISSING: ExceptionCode.MISSING_SEAL_NO,
        ChecklistItemCode.CONTAINER_TYPE_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.CONTAINER_COUNT_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.PIECES_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.WEIGHT_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.VOLUME_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.HS_CODE_MISMATCH: ExceptionCode.SO_MISMATCH,
        ChecklistItemCode.SI_MISSING: ExceptionCode.SI_OVERDUE,
        ChecklistItemCode.VGM_MISSING: ExceptionCode.VGM_OVERDUE,
    }
    ex_code = code_map.get(item.code)
    if not ex_code:
        return None  # 不映射的 code 不建异常 (e.g. dangerous_goods_flag_missing)

    ex = OperationalException(
        id=str(uuid.uuid4()),
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        code=ex_code,
        severity=ExceptionSeverity.CRITICAL,
        status=ExceptionStatus.OPEN,
        detected_at=datetime.now(timezone.utc),
        detected_by=ExceptionDetectedBy.SYSTEM,
        context={
            "source": "checklist_review",
            "review_id": review.id,
            "item_id": item.id,
            "checklist_code": item.code.value,
            "expected": item_data.get("expected_value"),
            "actual": item_data.get("actual_value"),
            "delta_pct": item_data.get("delta_pct"),
        },
    )
    db.add(ex)
    await db.flush()
    return ex


# ========== 操作员动作 ==========


async def acknowledge_item(
    db: AsyncSession,
    item: ChecklistItem,
    user_id: str,
    note: str | None = None,
) -> ChecklistItem:
    """操作员对某项确认 (warning 强制 pass)"""
    item.acknowledged_by_user_id = user_id
    item.acknowledged_at = datetime.now(timezone.utc)
    if note:
        item.note = note
    # 强制 pass
    if item.severity == ChecklistSeverity.WARNING:
        item.match = True
        # severity 保留 WARNING 但 match=True, 实际算作已确认
    await db.flush()
    return item


async def signoff_review(
    db: AsyncSession,
    review: ChecklistReview,
    user_id: str,
    user_name: str,
    note: str | None = None,
) -> ChecklistReview:
    """签收整个复核 (即使有 critical 也可签, 用于"已知问题, 决定发船")"""
    review.status = ChecklistReviewStatus.SIGNED_OFF
    review.signed_off_at = datetime.now(timezone.utc)
    review.reviewed_by_user_id = user_id
    review.reviewed_by_user_name = user_name
    if note:
        review.note = (review.note or "") + f"\n[签收] {note}"
    await db.flush()
    return review


# ========== 查询 ==========


async def list_reviews(
    db: AsyncSession,
    shipment_id: str,
    status: ChecklistReviewStatus | None = None,
    limit: int = 50,
) -> list[ChecklistReview]:
    stmt = (
        select(ChecklistReview)
        .where(ChecklistReview.shipment_id == shipment_id)
        .order_by(ChecklistReview.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(ChecklistReview.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def get_review_with_items(
    db: AsyncSession, review_id: str
) -> ChecklistReview | None:
    return (
        await db.execute(
            select(ChecklistReview).where(ChecklistReview.id == review_id)
        )
    ).scalar_one_or_none()
