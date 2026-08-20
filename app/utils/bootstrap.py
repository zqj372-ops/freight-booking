"""启动种子数据"""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.organization_context import get_default_organization
from app.models.email_template import EmailTemplate


DEFAULT_TEMPLATES = [
    {
        "code": "booking_request",
        "name": "订舱请求",
        "subject": "【订舱】{{ booking_no }} {{ carrier }} {{ pol }} → {{ pod }}",
        "body": """\
<p>您好，</p>

<p>二掌柜订舱系统代客户 <strong>{{ customer_name }}</strong> 申请订舱，详情如下：</p>

<table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;font-family:sans-serif;">
  <tr><th align="left">订舱号</th><td>{{ booking_no }}</td></tr>
  <tr><th align="left">船公司</th><td>{{ carrier }}</td></tr>
  <tr><th align="left">起运港 POL</th><td>{{ pol }}</td></tr>
  <tr><th align="left">目的港 POD</th><td>{{ pod }}</td></tr>
  <tr><th align="left">ETD</th><td>{{ etd }}</td></tr>
  <tr><th align="left">ETA</th><td>{{ eta }}</td></tr>
  <tr><th align="left">截关时间</th><td>{{ cut_off }}</td></tr>
  <tr><th align="left">箱型箱量</th><td>{{ container_count }} x {{ container_type }}</td></tr>
  <tr><th align="left">货物品名</th><td>{{ commodity }}</td></tr>
  <tr><th align="left">重量(KG)</th><td>{{ weight_kg }}</td></tr>
  <tr><th align="left">体积(CBM)</th><td>{{ volume_cbm }}</td></tr>
  <tr><th align="left">客户参考号</th><td>{{ customer_ref }}</td></tr>
</table>

<p>备注：{{ remark }}</p>
<p>请尽快回复舱位和价格，谢谢！</p>

<p>— {{ agent_name }} / 二掌柜订舱系统</p>
""",
    },
    {
        "code": "so_received",
        "name": "SO 收到确认",
        "subject": "【已收到】{{ carrier }} SO {{ so_number }}",
        "body": """\
<p>收到 {{ carrier }} 发送的 SO，编号 {{ so_number }}，航线 {{ pol }} → {{ pod }}，已入库系统。</p>
""",
    },
    {
        "code": "bill_notification",
        "name": "账单通知",
        "subject": "【账单】{{ bill_no }} - {{ total_amount }} {{ currency }}",
        "body": """\
<p>账单详情：</p>
<p>账单号：{{ bill_no }}</p>
<p>金额：{{ total_amount }} {{ currency }}</p>
<p>到期：{{ due_at }}</p>
""",
    },
]


async def seed_default_templates() -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await _seed(db)


async def _seed(db: AsyncSession) -> None:
    for tpl in DEFAULT_TEMPLATES:
        stmt = select(EmailTemplate).where(EmailTemplate.code == tpl["code"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            continue
        db.add(EmailTemplate(**tpl))
        await db.commit()
    logger.info("已加载默认邮件模板 {} 条", len(DEFAULT_TEMPLATES))


async def seed_default_organization() -> None:
    """v0.5 启动时 seed 默认组织 (幂等)"""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        org = await get_default_organization(db)
        logger.info("已加载默认组织: {} ({})", org.slug, org.display_name)
