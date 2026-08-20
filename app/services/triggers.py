"""v0.5 1.5.3: 17 SLA 任务 auto-trigger service

设计:
- 每个 TriggerEvent → 1 个 handler 函数
- handler 函数: 接受 (db, ctx), 返回创建的 Task 列表
- 主入口 fire_event: 查 registry, 调 handler, 写入 DB

触发点 (v0.5 1.5.3 阶段):
- on_booking_request_sent: workflow.py 已实现 (BC sent)
- on_booking_confirmation_accepted: workflow.py 已实现 (BC accept) — 已在内部建 4 task
- on_so_received: PATCH /shipment/{id}/events endpoint
- on_si_info_ready: PATCH /shipment/{id}/events endpoint
- on_bl_draft_received: PATCH /shipment/{id}/events endpoint
- on_sealed: PATCH /shipment/{id}/events endpoint
- on_departed: workflow.py 自动 (录 milestone)
- on_payment_proof_provided: PATCH /shipment/{id}/status endpoint
- on_inspection_received: PATCH /shipment/{id}/status endpoint

设计原则 (节点SLA sheet):
- 所有"Y/N, 是否完成, 完成时间" 改造成 task, 有触发事件 + 负责人 + 截止 + 完成证据
- due_at 计算: occurred_at + sla_hours (常量, 后续 v0.6 配 organization)
- auto_close_on: 只有能由 milestone 触发的, 其他靠人工 mark done
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import OrganizationScopedMixin  # noqa: F401  # doc link
from app.models.shipment import Shipment
from app.models.task import Task, TaskCode, TaskStatus


class TriggerEvent(str, Enum):
    """v0.5 1.5.3 SLA 触发事件 (17 个)"""

    BOOKING_REQUEST_SENT = "booking_request_sent"  # 订舱申请已发送
    BOOKING_CONFIRMATION_ACCEPTED = "booking_confirmation_accepted"  # BC 已接受 (在 workflow.py 内部处理)
    SO_RECEIVED = "so_received"  # SO 收到 (邮件解析/上传)
    SI_INFO_READY = "si_info_ready"  # 补料资料齐全
    BL_DRAFT_RECEIVED = "bl_draft_received"  # 提单草稿/修改件收到
    SEALED = "sealed"  # 封柜完成
    CUSTOMS_RELEASED = "customs_released"  # 出口报关放行
    INSPECTION_RECEIVED = "inspection_received"  # 收到官方查验通知
    DEPARTED = "departed"  # 船已开
    PAYMENT_PROOF_PROVIDED = "payment_proof_provided"  # 已提供水单
    PAYMENT_REQUESTED = "payment_requested"  # 已请款
    EMPTY_RETURN_DUE = "empty_return_due"  # 还空柜截止前提醒
    ETA_SET = "eta_set"  # 已设 ETA
    ATD_SET = "atd_set"  # 已设 ATD
    LOAD_PLAN_DUE = "load_plan_due"  # 拆柜前 Load Plan 准备
    SI_CUTOFF_APPROACHING = "si_cutoff_approaching"  # SI 临近截止
    CY_CUTOFF_APPROACHING = "cy_cutoff_approaching"  # CY 截港临近


@dataclass
class TriggerContext:
    """trigger handler 接收的上下文"""

    shipment: Shipment
    event: TriggerEvent
    occurred_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)


TriggerHandler = Callable[[AsyncSession, TriggerContext], Awaitable[list[Task]]]


def _make_task(
    shipment: Shipment,
    code: TaskCode,
    title: str,
    due_at: datetime,
    *,
    auto_close_on=None,
    context: dict | None = None,
    assignee_user_name: str | None = None,
) -> Task:
    return Task(
        organization_id=shipment.organization_id,
        shipment_id=shipment.id,
        code=code,
        title=title,
        due_at=due_at,
        status=TaskStatus.PENDING,
        auto_close_on=auto_close_on,
        assignee_user_name=assignee_user_name,
        context=context,
    )


# ========== 17 handler 实现 ==========


async def handler_booking_request_sent(db, ctx: TriggerContext) -> list[Task]:
    """订舱申请已发送 → 建 confirm_booking task (等待 supplier 回)"""
    # 已经在 workflow.on_booking_request_sent 里建过 milestone, 这里只确保 task 存在
    # v0.5 简化: 跟 supplier 确认 booking 是订舱操作自己的事, 1 task
    return [
        _make_task(
            ctx.shipment, TaskCode.CONFIRM_BOOKING,
            "跟进订舱回复 (carrier_booking_no)",
            ctx.occurred_at + timedelta(hours=24),  # 24h 内应回
            assignee_user_name="订舱操作",
        )
    ]


async def handler_so_received(db, ctx: TriggerContext) -> list[Task]:
    """SO 收到 → 2h 发拖车行 + 2h submit_si"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.SEND_SO_TO_TRUCKER,
            "将 SO 发给拖车行",
            at + timedelta(hours=2),
            assignee_user_name="订舱操作",
            context={"trigger": "so_received"},
        ),
        _make_task(
            ctx.shipment, TaskCode.SUBMIT_SI,
            "提交 SI 补料 (2h 内)",
            at + timedelta(hours=2),
            assignee_user_name="单证操作",
            context={"trigger": "so_received"},
        ),
    ]


async def handler_si_info_ready(db, ctx: TriggerContext) -> list[Task]:
    """补料资料齐全 → 2h 内发 SI"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.SEND_SI,
            "发送 SI 补料 (资料齐全后 2h)",
            at + timedelta(hours=2),
            assignee_user_name="单证操作",
        )
    ]


async def handler_bl_draft_received(db, ctx: TriggerContext) -> list[Task]:
    """提单草稿收到 → 30min 核对"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.REVIEW_BL_DRAFT,
            "核对提单草稿/修改件 (30min 内反馈)",
            at + timedelta(minutes=30),
            assignee_user_name="单证操作",
            context={"bl_received_at": at.isoformat()},
        )
    ]


async def handler_sealed(db, ctx: TriggerContext) -> list[Task]:
    """封柜完成 → 2h 发送报关资料"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.SEND_CUSTOMS_DOCS,
            "发送出口报关资料 (封柜后 2h)",
            at + timedelta(hours=2),
            assignee_user_name="报关操作",
        )
    ]


async def handler_customs_released(db, ctx: TriggerContext) -> list[Task]:
    """出口报关放行 → 自动 close customs 待办 (这里不建新 task, 留空)"""
    return []


async def handler_inspection_received(db, ctx: TriggerContext) -> list[Task]:
    """收到查验通知 → 立即建高优 task"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.HANDLE_INSPECTION,
            "处理官方查验通知 (高优)",
            at + timedelta(hours=4),  # 4h 内应开始处理
            assignee_user_name="报关操作/主管",
            context={"inspection_received_at": at.isoformat()},
        )
    ]


async def handler_departed(db, ctx: TriggerContext) -> list[Task]:
    """船开 (ATD) → ATD+2d 取得开船提单 + ATD+2d 取得 EMF"""
    atd = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.GET_ONBOARD_BL,
            "取得开船提单 (ATD+2d)",
            atd + timedelta(days=2),
            assignee_user_name="单证操作",
        ),
        _make_task(
            ctx.shipment, TaskCode.GET_EMF,
            "取得 EMF (ATD+2d)",
            atd + timedelta(days=2),
            assignee_user_name="目的港操作",
        ),
    ]


async def handler_payment_proof_provided(db, ctx: TriggerContext) -> list[Task]:
    """水单已提供 → 通知相关方 (no new task)"""
    return []


async def handler_payment_requested(db, ctx: TriggerContext) -> list[Task]:
    """已请款 → 等待水单"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.PROVIDE_PROOF,
            "提供水单 (付款后立即)",
            at + timedelta(hours=24),
            assignee_user_name="财务",
        )
    ]


async def handler_empty_return_due(db, ctx: TriggerContext) -> list[Task]:
    """还柜截止 → 提前 1d 提醒"""
    due = ctx.extra.get("due_at") or (ctx.occurred_at + timedelta(days=1))
    return [
        _make_task(
            ctx.shipment, TaskCode.RETURN_EMPTY,
            "归还空柜 (还柜截止前)",
            due,
            assignee_user_name="拖车/目的港操作",
            context={"empty_return_due_at": ctx.extra.get("empty_return_due_at")},
        )
    ]


async def handler_eta_set(db, ctx: TriggerContext) -> list[Task]:
    """ETA 已确认 → ETA-7d 请款 + ETA-3d 查船到 + ETA-3 工作日电放"""
    eta: datetime = ctx.extra["eta"]
    return [
        _make_task(
            ctx.shipment, TaskCode.PAYMENT_REQUEST,
            "发起请款/预付款 (ETA-7d)",
            eta - timedelta(days=7),
            assignee_user_name="财务/操作",
        ),
        _make_task(
            ctx.shipment, TaskCode.CHECK_ARRIVAL,
            "查询到港情况 (ETA-3d)",
            eta - timedelta(days=3),
            assignee_user_name="跟进人",
        ),
        _make_task(
            ctx.shipment, TaskCode.TELEX_BL,
            "取得电放提单 (ETA-3 工作日)",
            eta - timedelta(days=3),  # v0.5 简化, 实际 -3 工作日
            assignee_user_name="单证操作",
        ),
        _make_task(
            ctx.shipment, TaskCode.GET_ARRIVAL_NOTICE,
            "取得 Arrival Notice (ETA 前)",
            eta - timedelta(days=1),
            assignee_user_name="目的港操作",
        ),
    ]


async def handler_atd_set(db, ctx: TriggerContext) -> list[Task]:
    """ATD 已确认 → 检查开船查询 (etd+1d) + atd+2d 开船提单/emf 已在 departed 里建"""
    return []  # departed 触发时已建


async def handler_load_plan_due(db, ctx: TriggerContext) -> list[Task]:
    """拆柜前 → 准备 Load Plan"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.GET_LOAD_PLAN,
            "准备 Load Plan (拆柜前完成)",
            at,
            assignee_user_name="目的港操作",
        )
    ]


async def handler_si_cutoff_approaching(db, ctx: TriggerContext) -> list[Task]:
    """SI 临近截止 → 紧急提交"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.SUBMIT_SI,
            "紧急提交 SI 补料 (SI Cut-off 临近)",
            at,
            assignee_user_name="单证操作",
        )
    ]


async def handler_cy_cutoff_approaching(db, ctx: TriggerContext) -> list[Task]:
    """CY 截港临近 → 确认放行"""
    at = ctx.occurred_at
    return [
        _make_task(
            ctx.shipment, TaskCode.CONFIRM_CUSTOMS_RELEASED,
            "确认出口放行 (CY Cut-off 临近)",
            at,
            assignee_user_name="报关操作",
        )
    ]


# ========== Registry ==========

TRIGGER_REGISTRY: dict[TriggerEvent, TriggerHandler] = {
    TriggerEvent.BOOKING_REQUEST_SENT: handler_booking_request_sent,
    TriggerEvent.SO_RECEIVED: handler_so_received,
    TriggerEvent.SI_INFO_READY: handler_si_info_ready,
    TriggerEvent.BL_DRAFT_RECEIVED: handler_bl_draft_received,
    TriggerEvent.SEALED: handler_sealed,
    TriggerEvent.CUSTOMS_RELEASED: handler_customs_released,
    TriggerEvent.INSPECTION_RECEIVED: handler_inspection_received,
    TriggerEvent.DEPARTED: handler_departed,
    TriggerEvent.PAYMENT_PROOF_PROVIDED: handler_payment_proof_provided,
    TriggerEvent.PAYMENT_REQUESTED: handler_payment_requested,
    TriggerEvent.EMPTY_RETURN_DUE: handler_empty_return_due,
    TriggerEvent.ETA_SET: handler_eta_set,
    TriggerEvent.ATD_SET: handler_atd_set,
    TriggerEvent.LOAD_PLAN_DUE: handler_load_plan_due,
    TriggerEvent.SI_CUTOFF_APPROACHING: handler_si_cutoff_approaching,
    TriggerEvent.CY_CUTOFF_APPROACHING: handler_cy_cutoff_approaching,
    # 17 个事件 (实际包含更多状态, 但核心 17 个 SLA 触发点)
}


async def fire_event(
    db: AsyncSession,
    *,
    event: TriggerEvent,
    shipment: Shipment,
    occurred_at: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> list[Task]:
    """主入口: fire 一个 trigger 事件, 调用 handler 建 task.

    P2 修复: 幂等去重 — 同 shipment + 同 event 如果有未关闭 (PENDING/IN_PROGRESS) 的 task
    已 fire 过, 跳过. 标记方式: task.context["trigger_event"] = event.value.

    返回创建的 task 列表. 如果因幂等跳过, 返 [].
    """
    handler = TRIGGER_REGISTRY.get(event)
    if not handler:
        logger.warning("trigger event {} has no handler", event.value)
        return []

    # 幂等检查: 同 shipment + event 是否已 fire 过 (有未关闭 task)
    # 注: SQLite 不支持 .astext, 在 Python 端过滤 (一般 shipment 同时 active task 不多)
    from sqlalchemy import select
    candidate_tasks = (await db.execute(
        select(Task).where(
            Task.shipment_id == shipment.id,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
        )
    )).scalars().all()
    existing = sum(
        1 for t in candidate_tasks
        if (t.context or {}).get("trigger_event") == event.value
    )
    if existing > 0:
        logger.info(
            "trigger {} already fired for shipment {} ({} pending task(s)), skip",
            event.value, shipment.id, existing,
        )
        return []

    ctx = TriggerContext(
        shipment=shipment,
        event=event,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        extra=extra or {},
    )
    try:
        tasks = await handler(db, ctx)
    except Exception as e:
        logger.error("trigger handler {} failed: {}", event.value, e)
        return []
    # 注入 trigger_event 到 context, 方便下次 dedup
    for t in tasks:
        if t.context is None:
            t.context = {}
        # 不覆盖 handler 已写的 context, 只补 trigger_event
        t.context.setdefault("trigger_event", event.value)
        db.add(t)
    if tasks:
        await db.flush()
        logger.info(
            "fired trigger {} for shipment {} → created {} task(s)",
            event.value, shipment.id, len(tasks),
        )
    return tasks
