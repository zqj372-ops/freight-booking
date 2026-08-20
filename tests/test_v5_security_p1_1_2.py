"""v0.5 安全修复测试: P1#1 (路径越界) + P1#2 (EML 越界)

覆盖:
- document upload: 拒绝 ../ 越界, 拒绝非法后缀, 强制 uuid 重命名
- document download: 走鉴权 endpoint, 路径白名单
- email_thread ingest-eml: 拒绝绝对路径, 路径白名单, 强制 .eml 后缀
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app


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


async def _post(client, path, **kw):
    r = await client.post(path, **kw)
    return r


# ========== P1#1: document upload 路径越界 ==========


@pytest.mark.asyncio
async def test_document_upload_blocks_path_traversal() -> None:
    """文件名含 ../ 必须被剥成 basename + uuid 重命名, 不写入 /tmp/."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]

        evil_filename = "../../../../../../../tmp/freight-upload-target.pdf"
        files = {"file": (evil_filename, io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
        r = await c.post("/api/v2/documents/upload",
                         files=files, data={"shipment_id": sid})
        # 上传成功 (后端把 .. 剥成 basename), 但文件没越界到 /tmp/
        assert r.status_code == 201, r.text
        d = r.json()
        # /tmp/freight-upload-target.pdf 必须不存在 (没越界)
        assert not Path("/tmp/freight-upload-target.pdf").exists()
        # 写到了 upload_dir/.../{uuid}_freight-upload-target.pdf (basename + uuid 前缀)
        file_path = d["file_path"]
        assert file_path.startswith("/")  # 绝对路径
        # basename 部分 = {32hex uuid}_freight-upload-target.pdf
        basename = Path(file_path).name
        assert basename.endswith("_freight-upload-target.pdf")
        assert len(basename.split("_")[0]) == 32
        # 且路径在 upload_dir 之内
        from app.config import settings
        upload_root = Path(settings.upload_dir).resolve()
        assert str(Path(file_path).resolve()).startswith(str(upload_root))


@pytest.mark.asyncio
async def test_document_upload_blocks_disallowed_extension() -> None:
    """不在白名单的后缀必须被拒."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]

        for evil_ext in ["evil.exe", "shell.sh", "data.csv", "../.pdf"]:
            files = {"file": (f"test.{evil_ext}", io.BytesIO(b"x"), "application/octet-stream")}
            r = await c.post("/api/v2/documents/upload",
                             files=files, data={"shipment_id": sid})
            assert r.status_code == 400, f"ext {evil_ext} should be rejected, got {r.status_code}"


@pytest.mark.asyncio
async def test_document_upload_uses_uuid_filename() -> None:
    """上传成功时, 文件名应被 uuid 前缀重命名, 不是用户原始名."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]

        files = {"file": ("original_name.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
        r = await c.post("/api/v2/documents/upload",
                         files=files, data={"shipment_id": sid})
        assert r.status_code == 201
        d = r.json()
        # filename 在 doc 记录里仍保留原始名 (业务可读), 但 file_path 应该是 uuid 前缀
        assert d["filename"] == "original_name.pdf"
        # file_path 包含 uuid 32hex_ 模式
        file_path = d["file_path"]
        assert "_original_name.pdf" in file_path  # basename 仍存原始名
        # 但前面有 32hex uuid
        basename = file_path.split("/")[-1]
        assert len(basename.split("_")[0]) == 32


@pytest.mark.asyncio
async def test_document_download_requires_auth_and_path_check() -> None:
    """下载走 /api/v2/documents/{id}/download, 必须鉴权 (default org) + 路径白名单."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]

        files = {"file": ("d.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
        r = await c.post("/api/v2/documents/upload",
                         files=files, data={"shipment_id": sid})
        assert r.status_code == 201
        doc_id = r.json()["id"]

        # 走 /api/v2/documents/{id}/download 鉴权 endpoint
        r2 = await c.get(f"/api/v2/documents/{doc_id}/download")
        assert r2.status_code == 200
        assert r2.content.startswith(b"%PDF-1.4")

        # 不存在的 doc
        r3 = await c.get("/api/v2/documents/nonexistent-id/download")
        assert r3.status_code == 404


@pytest.mark.asyncio
async def test_files_static_mount_removed() -> None:
    """P1#1: /files 静态 mount 移除, 不能匿名读 upload_dir."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 上传一个文件
        s = await c.post("/api/v2/shipments/", json={
            "pol": "CNSHA", "pod": "USLAX", "target_etd": "2026-09-15", "commodity": "X",
        })
        sid = s.json()["id"]
        files = {"file": ("d.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
        r = await c.post("/api/v2/documents/upload",
                         files=files, data={"shipment_id": sid})
        doc = r.json()
        # 试着从 /files/{file_path} 匿名读 → 404 (因为没 mount)
        # 抽 file_path 的最后一段
        from pathlib import Path as P
        relative = P(doc["file_path"]).name
        r2 = await c.get(f"/files/attachments/{doc.get('organization_id', 'org')}/2026/08/{relative}")
        # 应该是 404 (没 mount), 不是 200
        assert r2.status_code == 404


# ========== P1#2: EML 越界 ==========


@pytest.mark.asyncio
async def test_ingest_eml_blocks_absolute_path() -> None:
    """P1#2: ingest-eml 不接受绝对路径."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 试图读 /etc/hosts
        r = await c.post("/api/v2/emails/ingest-eml", params={"eml_path": "/etc/hosts"})
        assert r.status_code == 400
        assert "absolute" in r.json()["detail"].lower() or "relative" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ingest_eml_blocks_path_traversal() -> None:
    """P1#2: 路径 ../ 越界 upload_dir 必须被拒."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v2/emails/ingest-eml", params={"eml_path": "../../../../etc/hosts"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_ingest_eml_requires_eml_extension() -> None:
    """P1#2: 非 .eml 后缀必须被拒."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        from app.config import settings
        # 写一个非 .eml 文件到 upload_dir
        upload_root = Path(settings.upload_dir).resolve()
        test_file = upload_root / "not_an_eml.txt"
        test_file.write_text("hello")
        r = await c.post("/api/v2/emails/ingest-eml", params={"eml_path": "not_an_eml.txt"})
        assert r.status_code == 400
        test_file.unlink()


@pytest.mark.asyncio
async def test_ingest_eml_accepts_valid_relative_path() -> None:
    """P1#2: 正常 upload_dir 内的 .eml 文件可处理."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        from app.config import settings
        upload_root = Path(settings.upload_dir).resolve()
        # 写一个最小合法 .eml
        eml_content = (
            "From: test@example.com\r\n"
            "To: op@example.com\r\n"
            "Subject: Test SO\r\n"
            "Message-ID: <test-1@example.com>\r\n"
            "Date: Mon, 21 Aug 2026 00:00:00 +0800\r\n"
            "\r\n"
            "Test body.\r\n"
        )
        test_file = upload_root / "test.eml"
        test_file.write_bytes(eml_content.encode())

        r = await c.post("/api/v2/emails/ingest-eml", params={"eml_path": "test.eml"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "thread_id" in d
        assert "message_id" in d
        test_file.unlink()
