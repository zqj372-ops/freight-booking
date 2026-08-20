"""v0.5 烟雾测试 - 阶段 1.1 领域基座 (Organization/Partner/AuditLog)"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.audit import Actor, write_audit_log
from app.core.organization_context import DEFAULT_ORG_SLUG
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import AuditLog, Organization, Partner
from app.models._base import AuditAction, AuditActorType, PartnerType


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    """每个测试前清表重建 (开发测试用)"""
    from app import models  # noqa: F401  触发 model 注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # seed 默认组织
    from app.utils.bootstrap import seed_default_organization
    await seed_default_organization()
    yield


@pytest.mark.asyncio
async def test_health_still_works() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_default_org_auto_seeded() -> None:
    """启动时自动 seed default-company"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/organizations/default")
        assert r.status_code == 200
        data = r.json()
        assert data["slug"] == DEFAULT_ORG_SLUG
        assert data["display_name"] == "二掌柜货代"
        assert data["job_no_prefix"] == "FB"
        assert data["job_no_reset_policy"] == "daily"
        assert data["job_no_seq_digits"] == 4


@pytest.mark.asyncio
async def test_list_organizations_returns_one() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v2/organizations/")
        assert r.status_code == 200
        orgs = r.json()
        assert len(orgs) == 1
        assert orgs[0]["slug"] == DEFAULT_ORG_SLUG


@pytest.mark.asyncio
async def test_update_organization_audit_logged() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 拿 org id
        r = await c.get("/api/v2/organizations/default")
        org_id = r.json()["id"]

        # 改 display_name
        r = await c.patch(
            f"/api/v2/organizations/{org_id}",
            json={"display_name": "二掌柜国际货代"},
        )
        assert r.status_code == 200
        assert r.json()["display_name"] == "二掌柜国际货代"

        # 查 audit log
        r = await c.get(
            f"/api/v2/audit-logs/by-entity/organization/{org_id}"
        )
        assert r.status_code == 200
        logs = r.json()
        assert len(logs) >= 1
        update_log = next((l for l in logs if l["action"] == "update"), None)
        assert update_log is not None
        assert update_log["actor_type"] == "api"
        assert "display_name" in update_log["field_changes"]


@pytest.mark.asyncio
async def test_create_partner_with_audit() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v2/partners/",
            json={
                "partner_type": "agent_l1",
                "name": "中转代理 A",
                "short_code": "AGT-A",
                "primary_email": "booking@agt-a.com",
                "cc_emails": ["cc@agt-a.com"],
                "preferred_routes": ["CNSHA-USLAX", "CNSHA-CAVAN"],
                "preferred_carriers": ["MAERSK", "MSC"],
                "response_sla_hours": 24,
            },
            headers={"X-User-Id": "user-001", "X-User-Name": "xiaozhang"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "中转代理 A"
        assert data["partner_type"] == "agent_l1"
        assert data["is_active"] is True
        assert data["organization_id"]  # 不为空
        partner_id = data["id"]

        # 自动留 audit log
        r = await c.get(
            f"/api/v2/audit-logs/by-entity/partner/{partner_id}"
        )
        assert r.status_code == 200
        logs = r.json()
        assert len(logs) == 1
        assert logs[0]["action"] == "create"
        # X-User-Id 头被识别为 actor
        assert logs[0]["actor_type"] == "user"
        assert logs[0]["actor_user_id"] == "user-001"
        assert logs[0]["actor_user_name"] == "xiaozhang"


@pytest.mark.asyncio
async def test_partner_short_code_unique() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v2/partners/",
            json={"partner_type": "agent_l1", "name": "代理 X", "short_code": "DUP"},
        )
        assert r.status_code == 201

        r = await c.post(
            "/api/v2/partners/",
            json={"partner_type": "agent_l1", "name": "代理 Y", "short_code": "DUP"},
        )
        assert r.status_code == 409
        assert "already exists" in r.json()["detail"]


@pytest.mark.asyncio
async def test_partner_list_filter_by_type() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 建 3 个不同类型
        for t, n in [("customer", "客户A"), ("carrier", "MAERSK"), ("agent_l1", "代理A")]:
            await c.post(
                "/api/v2/partners/",
                json={"partner_type": t, "name": n},
            )

        r = await c.get("/api/v2/partners/?partner_type=agent_l1")
        assert r.status_code == 200
        ps = r.json()
        assert len(ps) == 1
        assert ps[0]["name"] == "代理A"

        r = await c.get("/api/v2/partners/?is_active=true")
        assert len(r.json()) == 3


@pytest.mark.asyncio
async def test_partner_soft_delete_audit() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/v2/partners/",
            json={"partner_type": "carrier", "name": "废弃船公司"},
        )
        partner_id = r.json()["id"]

        r = await c.delete(f"/api/v2/partners/{partner_id}")
        assert r.status_code == 204

        # 软删: 列表默认不返回 is_active=false
        r = await c.get("/api/v2/partners/?is_active=true")
        assert partner_id not in [p["id"] for p in r.json()]

        # 加 is_active=false 过滤能找到
        r = await c.get("/api/v2/partners/?is_active=false")
        assert partner_id in [p["id"] for p in r.json()]

        # audit log 记录 DELETE
        r = await c.get(f"/api/v2/audit-logs/by-entity/partner/{partner_id}")
        logs = r.json()
        actions = [l["action"] for l in logs]
        assert "create" in actions
        assert "delete" in actions
        delete_log = next(l for l in logs if l["action"] == "delete")
        assert delete_log["reason"] == "soft delete via API"


@pytest.mark.asyncio
async def test_write_audit_log_helper() -> None:
    """直接测 service 层 helper"""
    from app.models.organization import Organization
    async with AsyncSessionLocal() as db:
        org = (await db.execute(select(Organization).where(Organization.slug == DEFAULT_ORG_SLUG))).scalar_one()
        await write_audit_log(
            db,
            organization_id=org.id,
            entity_type="test_entity",
            entity_id="test-001",
            action=AuditAction.RECORD,
            actor=Actor.system("unit_test"),
            field_changes={"foo": {"old": 1, "new": 2}},
            reason="just testing",
        )
        await db.commit()

        # 查回来
        stmt = select(AuditLog).where(
            AuditLog.entity_type == "test_entity",
            AuditLog.entity_id == "test-001",
        )
        log = (await db.execute(stmt)).scalar_one()
        assert log.action == AuditAction.RECORD
        assert log.actor_type == AuditActorType.SYSTEM
        assert log.actor_job_name == "unit_test"
        assert log.field_changes == {"foo": {"old": 1, "new": 2}}
        assert log.reason == "just testing"
