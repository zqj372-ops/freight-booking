"""v0.5 阶段 1.3 测试 - Document + EmailThread + EmailMessage"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from email.message import EmailMessage as PyEmailMessage
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.organization_context import DEFAULT_ORG_SLUG
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    Document,
    DocumentExtraction,
    EmailMessage,
    EmailThread,
    Organization,
    Shipment,
)
from app.services.document_service import (
    extract_job_no_from_subject,
    parse_so_fields,
)


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


@pytest.mark.asyncio
async def test_extract_job_no_from_subject() -> None:
    assert extract_job_no_from_subject("[FB-20260820-0001] Booking Request") == "FB-20260820-0001"
    assert extract_job_no_from_subject("Re: [MAE-20260820-XYZ] SO") == "MAE-20260820-XYZ"
    assert extract_job_no_from_subject("无前缀") is None
    assert extract_job_no_from_subject("") is None


@pytest.mark.asyncio
async def test_parse_so_fields() -> None:
    text = """
    MAERSK LINE Booking Confirmation
    Booking No: MAE123456789
    Vessel: MAERSK HONG KONG V.345E
    Port of Loading: SHANGHAI (CNSHA)
    Port of Discharge: LOS ANGELES (USLAX)
    ETD: 2026-09-15
    ETA: 2026-10-05
    Container: 1 x 40HQ
    """
    fields = parse_so_fields(text)
    assert "carrier" in fields
    assert "carrier_booking_no" in fields
    assert fields["carrier_booking_no"]["value"] == "MAE123456789"
    assert "CNSHA" in fields["pol"]["value"] or "SHANGHAI" in fields["pol"]["value"]
    assert fields["container_type"]["value"].endswith("40HQ")


@pytest.mark.asyncio
async def test_upload_document_then_extract_then_match() -> None:
    """手动上传 PDF, 跑抽取, 匹配到 Shipment (通过 carrier_booking_no)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 先建 Shipment (carrier_booking_no = MAE123)
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        await c.patch(f"/api/v2/shipments/{s['id']}", json={"carrier_booking_no": "MAE123456789"})

        # 上传 PDF
        pdf_content = b"""%PDF-1.4
MAERSK LINE Booking Confirmation
Booking No: MAE123456789
Vessel: MAERSK HONG KONG V.345E
Port of Loading: SHANGHAI (CNSHA)
Port of Discharge: LOS ANGELES (USLAX)
ETD: 2026-09-15
Container: 1 x 40HQ
%%EOF"""
        files = {"file": ("test.pdf", pdf_content, "application/pdf")}
        data = {"doc_type": "so"}
        r = await c.post("/api/v2/documents/upload", files=files, data=data)
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc["filename"] == "test.pdf"
        assert doc["doc_type"] == "so"
        assert doc["ocr_status"] == "done"  # 自动跑
        ocr_text = doc["ocr_text"] or ""
        # mock PDF 可能抽不到, 但抽取记录一定有
        # 抽取记录
        exts = (await c.get(f"/api/v2/documents/{doc['id']}/extractions")).json()
        assert len(exts) >= 1
        # 如果 pdfplumber 抽到, 字段有 carrier_booking_no
        if exts[0]["fields"]:
            assert "carrier_booking_no" in exts[0]["fields"]

        # 因为没传 shipment_id, 没自动匹配 (carriere hint 也没), 查 shipment_id 是 null
        assert doc["shipment_id"] is None

        # 手动匹配
        r = await c.post(f"/api/v2/documents/{doc['id']}/match", json={
            "shipment_id": s["id"], "confidence": 0.9,
        })
        assert r.status_code == 200
        assert r.json()["shipment_id"] == s["id"]
        assert r.json()["parse_status"] == "matched_shipment"


@pytest.mark.asyncio
async def test_upload_document_unsupported_mime() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        files = {"file": ("test.exe", b"fake exe", "application/octet-stream")}
        data = {"doc_type": "so"}
        r = await c.post("/api/v2/documents/upload", files=files, data=data)
        assert r.status_code == 400
        assert "unsupported" in r.json()["detail"]


@pytest.mark.asyncio
async def test_email_thread_create_for_shipment() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        r = await c.post(f"/api/v2/emails/threads/from-shipment/{s['id']}")
        assert r.status_code == 200
        thread = r.json()
        assert thread["subject"] == f"[{s['job_no']}]"
        assert thread["subject_prefix"] == s["job_no"]  # 解析出来了
        assert thread["shipment_id"] == s["id"]


@pytest.mark.asyncio
async def test_ingest_eml_creates_thread_and_message() -> None:
    """手动灌一个 .eml 文件, 创建 EmailThread + EmailMessage, 自动匹配"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 先建 shipment, job_no 用于主题前缀
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        job_no = s["job_no"]

        # 构造一个 .eml
        eml = PyEmailMessage()
        eml["From"] = "agent@maersk.com"
        eml["To"] = "ops@mycompany.com"
        eml["Subject"] = f"[{job_no}] SO Confirmation"
        eml["Message-ID"] = "<test-001@maersk.com>"
        eml["Date"] = "Thu, 20 Aug 2026 10:00:00 +0000"
        eml.set_content("Hello, here is the SO confirmation.\n\nBooking No: MAE999")

        eml_path = Path("/tmp/test_v5_1_3.eml")
        eml_path.write_bytes(bytes(eml))

        try:
            r = await c.post(f"/api/v2/emails/ingest-eml?eml_path={eml_path}")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["matched_shipment_id"] == s["id"]
            assert data["match_confidence"] >= 0.9

            # 查 thread (subject prefix 自动解析)
            thread = (await c.get(f"/api/v2/emails/threads/{data['thread_id']}")).json()
            assert thread["subject_prefix"] == job_no
            assert thread["shipment_id"] == s["id"]
            assert len(thread["messages"]) == 1
            msg = thread["messages"][0]
            assert msg["direction"] == "inbound"
            assert msg["from_addr"] == "agent@maersk.com"
            assert msg["matched_shipment_id"] == s["id"]
            assert msg["status"] == "processed"  # 自动匹配成功
        finally:
            eml_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_email_thread_in_reply_to_links() -> None:
    """inbound 邮件通过 In-Reply-To 找父邮件 → 取父的 shipment"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        job_no = s["job_no"]

        # 第一封 outbound (手动灌入, message_id 已知)
        eml1 = PyEmailMessage()
        eml1["From"] = "ops@mycompany.com"
        eml1["To"] = "agent@maersk.com"
        eml1["Subject"] = f"[{job_no}] Booking Request"
        eml1["Message-ID"] = "<out-001@mycompany.com>"
        eml1["Date"] = "Thu, 20 Aug 2026 09:00:00 +0000"
        eml1.set_content("Please book this shipment")
        eml1_path = Path("/tmp/test_v5_out.eml")
        eml1_path.write_bytes(bytes(eml1))
        try:
            r1 = await c.post(f"/api/v2/emails/ingest-eml?eml_path={eml1_path}")
            assert r1.status_code == 200
            assert r1.json()["matched_shipment_id"] == s["id"]
        finally:
            eml1_path.unlink(missing_ok=True)

        # 第二封 inbound, In-Reply-To 引用第一封
        eml2 = PyEmailMessage()
        eml2["From"] = "agent@maersk.com"
        eml2["To"] = "ops@mycompany.com"
        eml2["Subject"] = f"Re: [{job_no}] Booking Request"
        eml2["Message-ID"] = "<in-002@maersk.com>"
        eml2["In-Reply-To"] = "<out-001@mycompany.com>"
        eml2["Date"] = "Thu, 20 Aug 2026 10:00:00 +0000"
        eml2.set_content("Confirmed, see SO attached")
        eml2_path = Path("/tmp/test_v5_in.eml")
        eml2_path.write_bytes(bytes(eml2))
        try:
            r2 = await c.post(f"/api/v2/emails/ingest-eml?eml_path={eml2_path}")
            assert r2.status_code == 200
            # 跟第一封同一个 thread
            assert r2.json()["thread_id"] == r1.json()["thread_id"]
            assert r2.json()["matched_shipment_id"] == s["id"]
            # 跟第一封同一个 thread
            thread = (await c.get(f"/api/v2/emails/threads/{r2.json()['thread_id']}")).json()
            assert len(thread["messages"]) == 2
        finally:
            eml2_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_list_messages_by_thread() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = (await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })).json()
        thread = (await c.post(f"/api/v2/emails/threads/from-shipment/{s['id']}")).json()

        # 灌入 1 封邮件
        eml = PyEmailMessage()
        eml["From"] = "x@example.com"
        eml["To"] = "y@example.com"
        eml["Subject"] = f"[{s['job_no']}] Test"
        eml["Message-ID"] = "<test-x@x.com>"
        eml.set_content("test")
        eml_path = Path("/tmp/test_list.eml")
        eml_path.write_bytes(bytes(eml))
        try:
            r1 = await c.post(f"/api/v2/emails/ingest-eml?eml_path={eml_path}")
            assert r1.status_code == 200
            actual_thread_id = r1.json()["thread_id"]

            # list messages by thread (用 ingest 创建的 thread_id)
            r = await c.get(f"/api/v2/emails/messages?thread_id={actual_thread_id}")
            assert r.status_code == 200
            msgs = r.json()
            assert len(msgs) == 1
            assert msgs[0]["direction"] == "inbound"
        finally:
            eml_path.unlink(missing_ok=True)
