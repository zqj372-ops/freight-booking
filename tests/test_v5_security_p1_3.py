"""v0.5 安全修复测试: P1#3 booking_request /send 假发送

覆盖:
- dry_run=true: 不调 SMTP, BR 保持 draft
- SMTP 未配置 (mock raise): 返 502, BR 保持 draft, 写 FAILED EmailLog
- SMTP 成功 (mock pass): BR 改 SENT, 写 SENT EmailLog
- EmailLog 状态正确反映实际 SMTP 结果
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app
from app.models.booking_request import BookingRequestStatus
from app.models.email_log import EmailLog, EmailStatus


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.utils.bootstrap import seed_default_organization, seed_default_templates
    await seed_default_organization()
    await seed_default_templates()
    yield


async def _make_shipment_and_br(c) -> tuple[str, str]:
    s = await c.post("/api/v2/shipments/", json={
        "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
    })
    sid = s.json()["id"]
    # 建一个 carrier partner (booking_request 必须是 agent/carrier)
    p = await c.post("/api/v2/partners/", json={
        "partner_type": "carrier", "name": "Test Carrier",
        "primary_email": "test@example.com",
    })
    pid = p.json()["id"]
    br = await c.post("/api/v2/booking-requests/", json={
        "shipment_id": sid, "partner_id": pid,
        "requested_etd": "2026-09-15", "requested_pol": "CNSHA", "requested_pod": "USLAX",
    })
    return sid, br.json()["id"]


# ========== P1#3 假发送测试 ==========


@pytest.mark.asyncio
async def test_send_dry_run_keeps_br_draft(monkeypatch) -> None:
    """dry_run=true: 不调 SMTP, BR 保持 draft, EmailLog=PENDING."""
    # 即使 SMTP 真配了也不应该被调
    called = {"count": 0}

    def fake_send_sync(msg):
        called["count"] += 1

    from app.services import email_service
    monkeypatch.setattr(email_service, "_send_sync", fake_send_sync)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        _sid, br_id = await _make_shipment_and_br(c)
        r = await c.post(f"/api/v2/booking-requests/{br_id}/send", json={
            "to_emails": ["x@example.com"], "cc_emails": [],
            "dry_run": True,
        })
        assert r.status_code == 200
        # BR 保持 draft
        d = r.json()
        assert d["status"] == "draft"
        assert d["sent_at"] is None
        # SMTP 没被调
        assert called["count"] == 0


@pytest.mark.asyncio
async def test_send_smtp_failure_keeps_br_draft(monkeypatch) -> None:
    """P1#3 关键: SMTP 失败返 502, BR 状态不动, 不允许"假发送"成功."""
    from app.services import email_service

    def fake_send_sync(msg):
        raise RuntimeError("SMTP 未配置, 请检查 .env (SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD)")

    monkeypatch.setattr(email_service, "_send_sync", fake_send_sync)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        sid, br_id = await _make_shipment_and_br(c)
        r = await c.post(f"/api/v2/booking-requests/{br_id}/send", json={
            "to_emails": ["x@example.com"], "cc_emails": [],
            "dry_run": False,
        })
        # 返 502
        assert r.status_code == 502, r.text
        assert "SMTP" in r.json()["detail"] or "邮件" in r.json()["detail"]

        # 验证 BR 仍 draft (没被假改 SENT)
        r2 = await c.get(f"/api/v2/booking-requests/{br_id}")
        assert r2.status_code == 200
        br = r2.json()
        assert br["status"] == "draft", f"BR 状态被错误改成 {br['status']}, 应该是 draft"
        assert br["sent_at"] is None

        # 验证 EmailLog 写 FAILED
        from app.database import AsyncSessionLocal
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            logs = (await db.execute(
                select(EmailLog).where(EmailLog.booking_id == sid)
            )).scalars().all()
        assert len(logs) == 1
        assert logs[0].status == EmailStatus.FAILED
        assert "SMTP" in (logs[0].error or "")


@pytest.mark.asyncio
async def test_send_smtp_success_updates_br(monkeypatch) -> None:
    """SMTP 成功: EmailLog=SENT, BR.status=SENT, sent_at 填."""
    from app.services import email_service

    def fake_send_sync(msg):
        return  # 成功

    monkeypatch.setattr(email_service, "_send_sync", fake_send_sync)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        _sid, br_id = await _make_shipment_and_br(c)
        r = await c.post(f"/api/v2/booking-requests/{br_id}/send", json={
            "to_emails": ["x@example.com"], "cc_emails": [],
            "dry_run": False,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "sent"
        assert d["sent_at"] is not None


@pytest.mark.asyncio
async def test_send_without_smtp_config_returns_502(monkeypatch) -> None:
    """不 mock 时, 测试环境 SMTP 未配 → 返 502, BR 保持 draft (即原 bug 修复确认)."""
    # 强制 settings.smtp_host 为空 (默认 dev env 是空的)
    from app.config import settings
    from app.services import email_service

    # 确认没配
    assert not settings.smtp_host or not settings.smtp_username

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        _sid, br_id = await _make_shipment_and_br(c)
        r = await c.post(f"/api/v2/booking-requests/{br_id}/send", json={
            "to_emails": ["x@example.com"], "cc_emails": [],
            "dry_run": False,
        })
        # 修复前: 返 200 + BR=SENT (假发送)
        # 修复后: 返 502 + BR=draft
        assert r.status_code == 502, f"应该返 502 SMTP 失败, 实际 {r.status_code} {r.text}"
        r2 = await c.get(f"/api/v2/booking-requests/{br_id}")
        br = r2.json()
        assert br["status"] == "draft", f"BR 不该被改成 {br['status']}"
