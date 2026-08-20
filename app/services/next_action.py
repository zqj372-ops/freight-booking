"""v0.5 1.5.4: next_action + countdown + 4 卡片 dashboard + document-checklist

设计:
- next_action: 从 open task 推导下一步动作 (主列表第 8 字段)
- next_due_at: 最近 due 的 task 时间
- countdown_hours: 距离 due 的小时数 (负数=逾期)
- priority: 紧急 / 重要 / 一般 / 风险 (按 due 距离 + exception)
- dashboard 4 卡片: 逾期任务 / 今日到期 / 待 SO / 7 日内到港
- document_checklist: SO / BL / EMF / AN / Load Plan / VGM / SI / Customs 8 类文件齐套度
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking_confirmation import BookingConfirmation
from app.models.container import Container
from app.models.document import Document
from app.models.operational_exception import ExceptionStatus, OperationalException
from app.models.partner import Partner
from app.models.shipment import Shipment
from app.models.task import Task, TaskStatus


# ========== 优先级 / 状态枚举 (UI 渲染) ==========


class ActionPriority(str, enum.Enum):
    """next_action 优先级 (4 个, 主列表右侧栏/进度条颜色规则)"""

    URGENT = "urgent"  # 紧急 — 逾期 / open exception
    IMPORTANT = "important"  # 重要 — 4h 内 due
    NORMAL = "normal"  # 一般 — 正常进行
    RISK = "risk"  # 风险 — ETA 延后 / SI Cut-off 临近
    WAITING_EXTERNAL = "waiting_external"  # 紫 — 等待外部
    NONE = "none"  # 无


class DocStatus(str, enum.Enum):
    """文件齐套度 (8 类)"""

    COMPLETED = "completed"  # 1/1
    PARTIAL = "partial"  # 0/1 (有但缺)
    MISSING = "missing"  # 0/0
    NOT_APPLICABLE = "not_applicable"  # 不适用 (如未开船前 EMF)


# ========== 1.5.4a: next_action ==========


@dataclass
class NextAction:
    action: str
    due_at: datetime | None
    priority: ActionPriority
    countdown_hours: float | None  # 正=未来, 负=逾期
    task_id: str | None
    phase: int | None
    phase_label: str | None
    phase_color: str | None


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def derive_next_action(
    shipment: Shipment,
    open_tasks: list[Task],
    has_open_exception: bool,
    *,
    business_phase: int | None = None,
    phase_label: str | None = None,
    phase_color: str | None = None,
) -> NextAction:
    """从 open tasks + exception 推导下一步动作.

    优先级:
    1. 有 open exception → "处理异常" (urgent)
    2. 找最近 due_at 的 pending task
    3. 没有 task → "无待办" (none)
    """
    now = datetime.now(timezone.utc)

    if has_open_exception:
        return NextAction(
            action="处理异常",
            due_at=None,
            priority=ActionPriority.URGENT,
            countdown_hours=None,
            task_id=None,
            phase=business_phase,
            phase_label=phase_label,
            phase_color=phase_color,
        )

    pending = [t for t in open_tasks if t.status == TaskStatus.PENDING]
    if not pending:
        # 找 done / cancelled 都不算
        if business_phase == 8:
            return NextAction(
                action="结案完成",
                due_at=None, priority=ActionPriority.NONE,
                countdown_hours=None, task_id=None,
                phase=business_phase, phase_label=phase_label, phase_color=phase_color,
            )
        return NextAction(
            action="无待办",
            due_at=None, priority=ActionPriority.NORMAL,
            countdown_hours=None, task_id=None,
            phase=business_phase, phase_label=phase_label, phase_color=phase_color,
        )

    # 找最近 due 的 task
    def _due_key(t: Task) -> datetime:
        return _ensure_aware(t.due_at) or datetime.max.replace(tzinfo=timezone.utc)

    next_task = min(pending, key=_due_key)
    due = _ensure_aware(next_task.due_at)
    countdown: float | None = None
    if due is not None:
        countdown = round((due - now).total_seconds() / 3600, 2)

    # 优先级
    if countdown is not None and countdown < 0:
        priority = ActionPriority.URGENT
    elif countdown is not None and countdown < 4:
        priority = ActionPriority.IMPORTANT
    elif next_task.assignee_user_name and "外部" in next_task.assignee_user_name:
        priority = ActionPriority.WAITING_EXTERNAL
    else:
        priority = ActionPriority.NORMAL

    return NextAction(
        action=next_task.title,
        due_at=due,
        priority=priority,
        countdown_hours=countdown,
        task_id=next_task.id,
        phase=business_phase,
        phase_label=phase_label,
        phase_color=phase_color,
    )


# ========== 1.5.4b: dashboard 4 卡片 ==========


@dataclass
class DashboardStats:
    overdue_tasks: int
    due_today: int
    awaiting_so: int
    arriving_within_7d: int
    overdue_tasks_top: list[dict]  # 前 5 个逾期 task 详情
    due_today_top: list[dict]  # 前 5 个今日到期


async def derive_dashboard(
    db: AsyncSession,
    organization_id: str,
) -> DashboardStats:
    """4 卡片统计 (主列表顶部)

    1. 逾期任务: status=pending AND due_at < now
    2. 今日到期: due_at between 今日 00:00 and 明日 00:00
    3. 待 SO: shipment booking_request_sent_at IS NOT NULL AND so_received_at IS NULL
    4. 7 日内到港: eta between now and now+7d AND stage NOT IN (cancelled/completed)
    """
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    tomorrow_start = today_start + timedelta(days=1)
    seven_days_later = now + timedelta(days=7)

    # 1. 逾期任务
    stmt = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.organization_id == organization_id,
            Task.status == TaskStatus.PENDING,
            Task.due_at.isnot(None),
            Task.due_at < now,
        )
    )
    overdue_count = (await db.execute(stmt)).scalar() or 0

    # 1.top: 5 个逾期 task, 按 due_at 升序, join shipment
    from app.models.shipment import Shipment as ShipmentModel
    stmt_top = (
        select(Task, ShipmentModel.job_no, ShipmentModel.pol, ShipmentModel.pod)
        .join(ShipmentModel, Task.shipment_id == ShipmentModel.id)
        .where(
            Task.organization_id == organization_id,
            Task.status == TaskStatus.PENDING,
            Task.due_at.isnot(None),
            Task.due_at < now,
        )
        .order_by(Task.due_at.asc())
        .limit(5)
    )
    rows = (await db.execute(stmt_top)).all()
    overdue_top = [
        {
            "task_id": t.id, "title": t.title, "due_at": t.due_at.isoformat() if t.due_at else None,
            "job_no": jn, "pol": pol, "pod": pod, "shipment_id": t.shipment_id,
        }
        for t, jn, pol, pod in rows
    ]

    # 2. 今日到期
    stmt = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.organization_id == organization_id,
            Task.status == TaskStatus.PENDING,
            Task.due_at.isnot(None),
            Task.due_at >= today_start,
            Task.due_at < tomorrow_start,
        )
    )
    due_today_count = (await db.execute(stmt)).scalar() or 0

    stmt_top = (
        select(Task, ShipmentModel.job_no, ShipmentModel.pol, ShipmentModel.pod)
        .join(ShipmentModel, Task.shipment_id == ShipmentModel.id)
        .where(
            Task.organization_id == organization_id,
            Task.status == TaskStatus.PENDING,
            Task.due_at.isnot(None),
            Task.due_at >= today_start,
            Task.due_at < tomorrow_start,
        )
        .order_by(Task.due_at.asc())
        .limit(5)
    )
    rows = (await db.execute(stmt_top)).all()
    due_today_top = [
        {
            "task_id": t.id, "title": t.title, "due_at": t.due_at.isoformat() if t.due_at else None,
            "job_no": jn, "pol": pol, "pod": pod, "shipment_id": t.shipment_id,
        }
        for t, jn, pol, pod in rows
    ]

    # 3. 待 SO (booking_request_sent 但未收到 SO)
    stmt = (
        select(func.count())
        .select_from(ShipmentModel)
        .where(
            ShipmentModel.organization_id == organization_id,
            ShipmentModel.booking_request_sent_at.isnot(None),
            ShipmentModel.so_received_at.is_(None),
            ShipmentModel.stage != "cancelled",
        )
    )
    awaiting_so = (await db.execute(stmt)).scalar() or 0

    # 4. 7 日内到港
    stmt = (
        select(func.count())
        .select_from(ShipmentModel)
        .where(
            ShipmentModel.organization_id == organization_id,
            ShipmentModel.eta.isnot(None),
            ShipmentModel.eta >= now.date(),
            ShipmentModel.eta <= seven_days_later.date(),
        )
    )
    arriving_7d = (await db.execute(stmt)).scalar() or 0

    return DashboardStats(
        overdue_tasks=overdue_count,
        due_today=due_today_count,
        awaiting_so=awaiting_so,
        arriving_within_7d=arriving_7d,
        overdue_tasks_top=overdue_top,
        due_today_top=due_today_top,
    )


# ========== 1.5.4c: document-checklist ==========


@dataclass
class DocumentChecklistItem:
    code: str  # so / bl_draft / bl_final / emf / si / vgm / an / load_plan
    label: str
    required: bool
    status: DocStatus
    count: int
    expected: int  # 1 = 单一; 0 = 不适用
    latest_doc_id: str | None
    latest_received_at: datetime | None


@dataclass
class DocumentChecklist:
    shipment_id: str
    items: list[DocumentChecklistItem]
    total_required: int
    total_completed: int
    completion: float  # 0.0-1.0


async def derive_document_checklist(
    db: AsyncSession,
    organization_id: str,
    shipment_id: str,
) -> DocumentChecklist:
    """8 类文件齐套度 (业务详情 "文件齐套" 列)

    - SO (1) - 来自 is_current BookingConfirmation
    - BL draft (1) - 来自 email/document
    - BL final / onboard BL (1) - 来自 ATD 后
    - EMF (1) - 来自 ATD 后
    - SI (1) - 来自 SUBMIT_SI task / document
    - VGM (1) - 来自 SUBMIT_VGM task / document
    - AN (1) - 来自 email/document, 临近到港
    - Load Plan (1) - 来自 email/document, 拆柜前

    v0.5 简化: 不解析 doc 内容, 用 Document 表的 kind 字段统计
    """
    # 查所有 document
    stmt = select(Document).where(
        Document.organization_id == organization_id,
        Document.shipment_id == shipment_id,
    )
    docs = (await db.execute(stmt)).scalars().all()
    docs_by_kind: dict[str, list[Document]] = {}
    for d in docs:
        # Document.kind 暂用 mime 或 doc_type; v0.5 简化: 从 filename 推断
        kind = _infer_doc_kind(d)
        docs_by_kind.setdefault(kind, []).append(d)

    # 查 BC
    stmt = (
        select(BookingConfirmation)
        .where(
            BookingConfirmation.organization_id == organization_id,
            BookingConfirmation.shipment_id == shipment_id,
            BookingConfirmation.is_current == True,  # noqa: E712
        )
    )
    bc = (await db.execute(stmt)).scalar_one_or_none()
    has_so = bc is not None

    # 查 ATD
    from app.models.milestone import Milestone, MilestoneCode
    stmt = (
        select(Milestone)
        .where(
            Milestone.organization_id == organization_id,
            Milestone.shipment_id == shipment_id,
            Milestone.code == MilestoneCode.DEPARTED,
        )
        .order_by(Milestone.occurred_at.desc())
        .limit(1)
    )
    departed_ms = (await db.execute(stmt)).scalar_one_or_none()
    has_departed = departed_ms is not None

    # 查 SI/VGM 提交
    stmt = (
        select(Milestone)
        .where(
            Milestone.organization_id == organization_id,
            Milestone.shipment_id == shipment_id,
            Milestone.code.in_([
                MilestoneCode.SI_SUBMITTED, MilestoneCode.VGM_SUBMITTED,
                MilestoneCode.CUSTOMS_CLEARED,
            ]),
        )
    )
    submitted = (await db.execute(stmt)).scalars().all()
    codes_submitted = {m.code for m in submitted}

    items_spec: list[tuple[str, str, bool, int]] = [
        ("so", "SO 确认书", True, 1),
        ("si", "SI 补料", True, 1),
        ("vgm", "VGM", True, 1),
        ("customs", "报关资料", True, 1),
        ("bl_draft", "提单草稿", True, 1),
        ("bl_final", "开船提单", True, 1 if has_departed else 0),
        ("emf", "EMF", True, 1 if has_departed else 0),
        ("an", "Arrival Notice", False, 1),  # 不强制
        ("load_plan", "Load Plan", False, 1),  # 拆柜前
    ]
    items: list[DocumentChecklistItem] = []
    total_required = 0
    total_completed = 0

    for code, label, required, expected in items_spec:
        # 状态: milestone 优先
        if code == "so":
            count = 1 if has_so else 0
        elif code == "si":
            count = 1 if MilestoneCode.SI_SUBMITTED in codes_submitted else 0
        elif code == "vgm":
            count = 1 if MilestoneCode.VGM_SUBMITTED in codes_submitted else 0
        elif code == "customs":
            count = 1 if MilestoneCode.CUSTOMS_CLEARED in codes_submitted else 0
        elif code == "bl_final":
            count = 1 if has_departed else 0
        elif code == "emf":
            count = 1 if has_departed else 0
        else:
            count = len(docs_by_kind.get(code, []))

        latest = None
        if docs_by_kind.get(code):
            latest = max(docs_by_kind[code], key=lambda d: d.created_at)

        if expected == 0:
            status = DocStatus.NOT_APPLICABLE
        elif count >= expected:
            status = DocStatus.COMPLETED
        elif count == 0:
            status = DocStatus.MISSING
        else:
            status = DocStatus.PARTIAL

        if required:
            total_required += expected
            total_completed += min(count, expected)

        items.append(DocumentChecklistItem(
            code=code, label=label, required=required, status=status,
            count=count, expected=expected,
            latest_doc_id=latest.id if latest else None,
            latest_received_at=latest.created_at if latest else None,
        ))

    completion = total_completed / total_required if total_required > 0 else 1.0
    return DocumentChecklist(
        shipment_id=shipment_id, items=items,
        total_required=total_required, total_completed=total_completed,
        completion=round(completion, 2),
    )


def _infer_doc_kind(doc: Document) -> str:
    """从 Document 推断 kind. v0.5 简化: 用 doc_type 优先, filename 关键字 fallback."""
    if hasattr(doc, "doc_type") and doc.doc_type:
        from app.models.document import DocumentType
        dt = doc.doc_type
        if isinstance(dt, str):
            try:
                dt = DocumentType(dt)
            except ValueError:
                dt = None
        if dt is not None:
            if dt == DocumentType.SO:
                return "so"
            if dt == DocumentType.SI:
                return "si"
            if dt == DocumentType.VGM:
                return "vgm"
            if dt == DocumentType.BL:
                return "bl_final"  # 简化: 都当 final, 后续版本化
            if dt == DocumentType.INVOICE:
                return "other"
            if dt == DocumentType.PACKING_LIST:
                return "other"
            if dt == DocumentType.OTHER:
                pass  # 走 filename fallback
    fn = (doc.filename or "").lower()
    if "bl" in fn and "draft" in fn:
        return "bl_draft"
    if "emf" in fn or "manifest" in fn:
        return "emf"
    if "an" in fn or "arrival" in fn:
        return "an"
    if "load" in fn or "plan" in fn:
        return "load_plan"
    if "customs" in fn or "declaration" in fn:
        return "customs"
    return "other"


# ========== 1.5.4d: 主列表 12 字段构造 ==========


@dataclass
class ShipmentListItem:
    """主列表 12 字段 (1.5.4 final)"""
    id: str
    job_no: str
    route_summary: str  # "CNSZX → CAVAN 1×40HQ"
    carrier_partner: str  # "COSCO 华南一级代理"
    vessel_voyage: str  # "COSCO SHIPPING... 082E"
    current_etd: str | None  # ISO date
    current_eta: str | None
    business_phase: int
    business_phase_label: str
    business_phase_color: str
    next_action: str
    next_due_at: str | None
    countdown_hours: float | None
    next_action_priority: str
    operator_user_name: str | None
    exception_label: str  # "一般/重要/紧急/—"
    progress: float  # 0.0-1.0
    last_updated_at: str | None


async def build_shipment_list_items(
    db: AsyncSession,
    organization_id: str,
    shipments: list[Shipment],
) -> list[ShipmentListItem]:
    """从一批 Shipment 构造主列表 12 字段 items.

    一次性查:
    - shipment id → tasks, exceptions, current BC, current_container
    - 用 in_ 一次查所有, 内存 join
    """
    if not shipments:
        return []

    from app.models.booking_confirmation import BookingConfirmation
    from app.models.container import Container
    from app.models.milestone import Milestone
    from app.models.operational_exception import OperationalException
    from app.models.task import Task

    ship_ids = [s.id for s in shipments]

    # 1. tasks
    stmt = select(Task).where(
        Task.organization_id == organization_id,
        Task.shipment_id.in_(ship_ids),
        Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
    )
    tasks = (await db.execute(stmt)).scalars().all()
    tasks_by_ship: dict[str, list[Task]] = {sid: [] for sid in ship_ids}
    for t in tasks:
        tasks_by_ship.setdefault(t.shipment_id, []).append(t)

    # 2. open exceptions
    stmt = select(OperationalException).where(
        OperationalException.organization_id == organization_id,
        OperationalException.shipment_id.in_(ship_ids),
        OperationalException.status == ExceptionStatus.OPEN,
    )
    opex = (await db.execute(stmt)).scalars().all()
    opex_by_ship: dict[str, int] = {sid: 0 for sid in ship_ids}
    for e in opex:
        opex_by_ship[e.shipment_id] = opex_by_ship.get(e.shipment_id, 0) + 1
        # 重要 = critical severity, 紧急 = warning + schedule/port/carrier
        if e.severity.value == "critical":
            opex_by_ship[e.shipment_id] = max(opex_by_ship[e.shipment_id], 3)

    # 3. current BC
    stmt = select(BookingConfirmation).where(
        BookingConfirmation.organization_id == organization_id,
        BookingConfirmation.shipment_id.in_(ship_ids),
        BookingConfirmation.is_current == True,  # noqa: E712
    )
    bcs = (await db.execute(stmt)).scalars().all()
    bc_by_ship: dict[str, BookingConfirmation] = {b.shipment_id: b for b in bcs}

    # 4. container (1.5 强制 1 柜)
    stmt = select(Container).where(
        Container.organization_id == organization_id,
        Container.shipment_id.in_(ship_ids),
    )
    containers = (await db.execute(stmt)).scalars().all()
    container_by_ship: dict[str, Container] = {c.shipment_id: c for c in containers}

    # 5. milestones (推导 business_phase)
    stmt = select(Milestone).where(
        Milestone.organization_id == organization_id,
        Milestone.shipment_id.in_(ship_ids),
    )
    ms_list = (await db.execute(stmt)).scalars().all()
    ms_by_ship: dict[str, list[Milestone]] = {sid: [] for sid in ship_ids}
    for m in ms_list:
        ms_by_ship.setdefault(m.shipment_id, []).append(m)

    # 6. partners (for carrier_partner 显示)
    partner_ids = {s.current_partner_id for s in shipments if s.current_partner_id}
    partners_by_id: dict[str, Partner] = {}
    if partner_ids:
        stmt = select(Partner).where(Partner.id.in_(partner_ids))
        partners = (await db.execute(stmt)).scalars().all()
        partners_by_id = {p.id: p for p in partners}

    from app.models._base import BusinessPhase, PhaseColor
    from app.services.workflow import PHASE_LABELS, derive_business_phase, derive_phase_color, derive_phase_progress

    items: list[ShipmentListItem] = []
    for s in shipments:
        # 路线/柜型
        c = container_by_ship.get(s.id)
        container_type = c.container_type if c else "40HQ"
        route = f"{s.pol} → {s.pod} {s.container_count}×{container_type}"

        # 船公司/代理
        carrier = s.current_carrier or "—"
        partner_name = ""
        if s.current_partner_id and s.current_partner_id in partners_by_id:
            partner_name = partners_by_id[s.current_partner_id].name
        carrier_partner = f"{carrier} {partner_name}".strip() if partner_name else carrier

        # 船名航次 (来自 current BC)
        bc = bc_by_ship.get(s.id)
        vessel_voyage = ""
        if bc:
            vessel_voyage = f"{bc.vessel or ''} {bc.voyage or ''}".strip()
        if not vessel_voyage:
            vessel_voyage = "—"

        # 当前 ETD / ETA (BC 优先, 否则 shipment.etd/eta)
        current_etd = (bc.etd if bc and bc.etd else s.etd)
        current_eta = (bc.eta if bc and bc.eta else s.eta)
        current_etd_str = current_etd.isoformat() if current_etd else None
        current_eta_str = current_eta.isoformat() if current_eta else None

        # business_phase
        milestones = ms_by_ship.get(s.id, [])
        bp = derive_business_phase(milestones)
        bp_progress = derive_phase_progress(milestones)
        bp_label = PHASE_LABELS.get(bp, str(bp.value))

        # next_due_at (从 open tasks 推最近 due)
        open_tasks = tasks_by_ship.get(s.id, [])
        next_due = None
        next_due_str = None
        countdown = None
        for t in open_tasks:
            if t.due_at is None:
                continue
            d = _ensure_aware(t.due_at)
            if next_due is None or d < next_due:
                next_due = d
        if next_due is not None:
            now = datetime.now(timezone.utc)
            countdown = round((next_due - now).total_seconds() / 3600, 2)
            next_due_str = next_due.isoformat()

        # next_action
        next_action_text = "无待办"
        if opex_by_ship.get(s.id, 0) > 0:
            next_action_text = "处理异常"
        elif open_tasks:
            # 找最近 due 的 task
            due_tasks = [t for t in open_tasks if t.due_at is not None]
            if due_tasks:
                nt = min(due_tasks, key=lambda t: _ensure_aware(t.due_at))
                next_action_text = nt.title
            elif open_tasks:
                next_action_text = open_tasks[0].title

        # priority
        priority = "normal"
        if opex_by_ship.get(s.id, 0) > 0:
            priority = "urgent"
        elif countdown is not None and countdown < 0:
            priority = "urgent"
        elif countdown is not None and countdown < 4:
            priority = "important"
        elif any("外部" in (t.assignee_user_name or "") for t in open_tasks):
            priority = "waiting_external"

        # exception_label
        exc_count = opex_by_ship.get(s.id, 0)
        if exc_count >= 3:
            exception_label = "紧急"
        elif exc_count == 2:
            exception_label = "重要"
        elif exc_count == 1:
            exception_label = "一般"
        else:
            exception_label = "—"

        # color
        has_opex = opex_by_ship.get(s.id, 0) > 0
        color = derive_phase_color(bp, next_due, has_opex).value

        items.append(ShipmentListItem(
            id=s.id,
            job_no=s.job_no,
            route_summary=route,
            carrier_partner=carrier_partner,
            vessel_voyage=vessel_voyage,
            current_etd=current_etd_str,
            current_eta=current_eta_str,
            business_phase=bp.value,
            business_phase_label=bp_label,
            business_phase_color=color,
            next_action=next_action_text,
            next_due_at=next_due_str,
            countdown_hours=countdown,
            next_action_priority=priority,
            operator_user_name=s.operator_user_name,
            exception_label=exception_label,
            progress=bp_progress,
            last_updated_at=s.last_updated_at.isoformat() if s.last_updated_at else None,
        ))

    return items
