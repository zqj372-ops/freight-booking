"""生成 IMAP mock 样本 .eml 文件 (含 PDF/图片附件)"""

import base64
import sys
from email.message import EmailMessage
from pathlib import Path


def make_minimal_pdf(text: str = "Test PDF") -> bytes:
    """生成一个最小可用的 PDF, 内含一段文字"""
    # 简化的 PDF, 不含中文字体
    content_stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin-1")
    stream = b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n" + content_stream + b"\nendstream"

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        b"4 0 obj\n" + stream + b"\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj

    xref_offset = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
    pdf += b"startxref\n"
    pdf += str(xref_offset).encode() + b"\n%%EOF\n"
    return pdf


def make_sample_eml(
    out_path: Path,
    subject: str,
    from_addr: str,
    message_id: str,
    pdf_text: str = "MAERSK SO Confirmation\nBooking: TEST-123\nPOL: CNSHA\nPOD: USLAX",
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "ops@mycompany.com"
    msg["Date"] = "Wed, 19 Aug 2026 10:00:00 +0800"
    msg["Message-ID"] = message_id
    msg.set_content(f"附件是 {subject}\n请查收")

    pdf_bytes = make_minimal_pdf(pdf_text)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"{message_id.strip('<>')}.pdf",
    )
    out_path.write_bytes(msg.as_bytes())
    print(f"✅ {out_path} ({len(msg.as_bytes())} bytes)")


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "./samples/imap")
    target.mkdir(parents=True, exist_ok=True)

    samples = [
        (
            "001_maersk_so.eml",
            "MAERSK SO Confirmation MAE-2026-001",
            "booking@maersk.com",
            "<maersk-so-001@maersk.com>",
        ),
        (
            "002_msc_so.eml",
            "MSC Booking Confirmation MSC-CN-2026-888",
            "booking@msc.com",
            "<msc-so-002@msc.com>",
        ),
        (
            "003_not_so.eml",
            "Newsletter: industry update",  # 不含关键词, 会被过滤
            "marketing@somewhere.com",
            "<news-003@somewhere.com>",
        ),
        (
            "004_cosco_so.eml",
            "中远海运 SO 订舱确认 COS-CN-2026-555",
            "booking@coscoshipping.com",
            "<cosco-so-004@cosco.com>",
        ),
    ]

    for name, subj, frm, mid in samples:
        make_sample_eml(target / name, subj, frm, mid)
    print(f"\n生成 {len(samples)} 个样本到 {target}")


if __name__ == "__main__":
    main()
