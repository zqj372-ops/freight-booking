"""Smoke test - 不依赖 OCR, 跑通最小流程"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.database import Base, engine, AsyncSessionLocal
    from app import models  # noqa: F401

    # 先清表 (开发测试用, 生产别这么干)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.utils.bootstrap import _seed
    async with AsyncSessionLocal() as s:
        await _seed(s)
    yield
    # 不清表, 方便调试; CI 加 cleanup


@pytest.mark.asyncio
async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_and_list_agent() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/agents/",
            json={"name": "测试代理", "code": "TEST", "booking_email": "test@example.com"},
        )
        assert r.status_code == 201
        agent_id = r.json()["id"]

        r = await c.get("/api/v1/agents/")
        assert r.status_code == 200
        assert any(a["id"] == agent_id for a in r.json())


@pytest.mark.asyncio
async def test_list_email_templates() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/emails/templates")
        assert r.status_code == 200
        codes = [t["code"] for t in r.json()]
        assert "booking_request" in codes


@pytest.mark.asyncio
async def test_so_parser_basic() -> None:
    """SO 文本解析 - 规则覆盖"""
    from app.services.so_parser import parse_so_text

    text = """
    MAERSK LINE Booking Confirmation

    Booking No: MAE123456789
    Vessel: MAERSK HONG KONG V.345E
    Port of Loading: SHANGHAI (CNSHA)
    Port of Discharge: LOS ANGELES (USLAX)
    ETD: 2026-09-15
    ETA: 2026-10-05

    Container: 2 x 40HQ
    Commodity: ELECTRONIC PARTS
    """
    fields = parse_so_text(text)
    assert fields["carrier"] == "MAERSK"
    assert fields["so_number"] == "MAE123456789"
    assert fields["vessel_name"] is not None
    assert "CNSHA" in (fields["pol"] or "").upper() or "SHANGHAI" in (fields["pol"] or "").upper()
    assert fields["container_type"] == "40HQ"
    assert fields["container_count"] == 2


@pytest.mark.asyncio
async def test_create_booking_and_state_machine() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 先建一个 agent
        r = await c.post(
            "/api/v1/agents/",
            json={"name": "中转代理", "booking_email": "booking@agent.com"},
        )
        agent_id = r.json()["id"]

        # 建订舱
        r = await c.post(
            "/api/v1/bookings/",
            json={
                "carrier": "MAERSK",
                "pol": "CNSHA",
                "pod": "USLAX",
                "agent_id": agent_id,
                "container_type": "40HQ",
                "container_count": 1,
            },
        )
        assert r.status_code == 201
        booking_id = r.json()["id"]
        assert r.json()["status"] == "draft"

        # 状态机: draft -> submitted
        r = await c.patch(
            f"/api/v1/bookings/{booking_id}",
            json={"status": "submitted"},
        )
        assert r.status_code == 200

        # 状态机: submitted -> draft (非法跳回 cancelled 不允许)
        r = await c.patch(
            f"/api/v1/bookings/{booking_id}",
            json={"status": "draft"},
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_booking_auto_creates_booked_event() -> None:
    """建订舱应该自动产生 BOOKED 跟踪节点"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v1/bookings/",
            json={"carrier": "MSC", "pol": "CNNGB", "pod": "DEHAM", "container_type": "20GP", "container_count": 2},
        )
        assert r.status_code == 201
        bid = r.json()["id"]

        # 查 status
        r = await c.get(f"/api/v1/tracking/bookings/{bid}/status")
        assert r.status_code == 200
        assert r.json()["current_status"] == "booked"

        # 查 events
        r = await c.get(f"/api/v1/tracking/bookings/{bid}/events")
        assert r.status_code == 200
        events = r.json()
        assert len(events) >= 1
        assert events[0]["status"] == "booked"


@pytest.mark.asyncio
async def test_tracking_state_machine() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建订舱
        r = await c.post(
            "/api/v1/bookings/",
            json={"carrier": "COSCO", "pol": "CNSHA", "pod": "USNYC"},
        )
        bid = r.json()["id"]

        # 推进 booked -> empty_picked_up
        r = await c.post(
            f"/api/v1/tracking/bookings/{bid}/events",
            json={"status": "empty_picked_up", "occurred_at": "2026-08-20T10:00:00", "location": "CNSHA 堆场"},
        )
        assert r.status_code == 201

        # 推进 empty_picked_up -> loaded
        r = await c.post(
            f"/api/v1/tracking/bookings/{bid}/events",
            json={"status": "loaded", "occurred_at": "2026-08-20T18:00:00", "vessel_name": "COSCO SHIPPING UNIVERSE"},
        )
        assert r.status_code == 201

        # 非法跳: loaded -> delivered (中间要经过 departed/in_transit/arrived)
        r = await c.post(
            f"/api/v1/tracking/bookings/{bid}/events",
            json={"status": "delivered", "occurred_at": "2026-09-01T10:00:00"},
        )
        assert r.status_code == 400  # 状态机拒绝

        # 正常推进到 completed (时间递增避免排序歧义)
        from datetime import datetime, timedelta

        base = datetime(2026, 8, 21, 10, 0, 0)
        for i, (status_, location) in enumerate(
            [
                ("departed", "CNSHA"),
                ("in_transit", None),
                ("arrived", "USNYC"),
                ("delivered", "USNYC 仓库"),
                ("completed", None),
            ]
        ):
            r = await c.post(
                f"/api/v1/tracking/bookings/{bid}/events",
                json={
                    "status": status_,
                    "occurred_at": (base + timedelta(hours=i)).isoformat(),
                    "location": location,
                },
            )
            assert r.status_code == 201, f"{status_} failed: {r.text}"

        # 最终状态
        r = await c.get(f"/api/v1/tracking/bookings/{bid}/status")
        assert r.json()["current_status"] == "completed"


@pytest.mark.asyncio
async def test_kanban_view() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建几个 booking
        for i, carrier in enumerate(["MAERSK", "MSC", "COSCO"]):
            r = await c.post(
                "/api/v1/bookings/",
                json={"carrier": carrier, "pol": "CNSHA", "pod": f"US{i:02d}"},
            )
            assert r.status_code == 201

        r = await c.get("/api/v1/tracking/kanban")
        assert r.status_code == 200
        data = r.json()
        assert "columns" in data
        assert len(data["columns"]) == 9  # 9 个状态
        # 至少 booked 列有数据
        booked_col = next(c for c in data["columns"] if c["status"] == "booked")
        assert booked_col["count"] >= 3


def test_bill_parser_vat_invoice() -> None:
    """增值税发票 OCR 文本解析"""
    from app.services.bill_parser import parse_bill_text

    text = """
    增值税专用发票
    发票代码: 011001900111
    发票号码: 12345678
    开票日期: 2026-08-19

    销售方 名称: 上海中远海运物流有限公司
    纳税人识别号: 91310101MA1FXXXXXX
    购买方 名称: 深圳市海星供应链有限公司
    纳税人识别号: 91440300MA5DXXXXXX

    货物名称 数量 单价 金额 税率 税额
    海运费 1 5000.00 5000.00 6% 300.00
    操作费 1 500.00 500.00 6% 30.00

    价税合计(大写) 伍仟捌佰叁拾圆整 （小写）¥5830.00
    税额 ¥330.00
    不含税金额 ¥5500.00
    """
    fields = parse_bill_text(text)
    assert fields["bill_no"] == "12345678"
    assert "中远海运" in (fields.get("seller_name") or "")
    assert "海星" in (fields.get("buyer_name") or "")
    assert fields["total_amount"] == 5830.00
    assert fields["tax_amount"] == 330.00
    assert fields["amount_excl_tax"] == 5500.00
    assert fields["currency"] == "CNY"
    assert fields["bill_kind"] == "vat_special"
    assert len(fields.get("line_items", [])) == 2


def test_bill_parser_ocean_freight() -> None:
    """海运费发票解析"""
    from app.services.bill_parser import parse_bill_text

    text = """
    OCEAN FREIGHT INVOICE
    Invoice No: MAE-INV-2026-001
    Date: 2026/08/19

    From: MAERSK LINE
    To: SHENZHEN LOGISTICS CO LTD

    Amount: USD 1500.00
    """
    fields = parse_bill_text(text)
    assert fields["bill_no"] == "MAE-INV-2026-001"
    assert fields["currency"] == "USD"
    assert fields["bill_kind"] == "ocean_freight"


@pytest.mark.asyncio
async def test_bill_crud() -> None:
    """账单 CRUD + OCR 状态"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 手动建
        r = await c.post(
            "/api/v1/bills/",
            json={
                "bill_no": "INV-2026-TEST-001",
                "bill_type": "receivable",
                "currency": "CNY",
                "total_amount": 1000.0,
                "tax_amount": 60.0,
                "amount_excl_tax": 940.0,
                "seller_name": "测试销售方",
                "buyer_name": "测试购买方",
            },
        )
        assert r.status_code == 201
        bid = r.json()["id"]
        assert r.json()["status"] == "uploaded"

        # 列表
        r = await c.get("/api/v1/bills/")
        assert r.status_code == 200
        assert any(b["id"] == bid for b in r.json()["items"])

        # 修正 + 确认
        r = await c.patch(f"/api/v1/bills/{bid}", json={"remark": "客户已确认"})
        assert r.status_code == 200
        r = await c.post(f"/api/v1/bills/{bid}/confirm")
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"
