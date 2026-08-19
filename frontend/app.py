"""Streamlit 前端 - 二掌柜订舱系统 MVP UI

用法: streamlit run frontend/app.py
默认连 http://localhost:8000 (FastAPI)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
API_V1 = f"{API_BASE}/api/v1"

st.set_page_config(
    page_title="二掌柜订舱系统",
    page_icon="🚢",
    layout="wide",
    initial_sidebar_state="expanded",
)


def api_get(path: str, **params) -> dict[str, Any]:
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{API_V1}{path}", params=params)
        r.raise_for_status()
        return r.json()


def api_post(path: str, json: dict | None = None, files: dict | None = None, data: dict | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=120) as c:
        if files:
            r = c.post(f"{API_V1}{path}", files=files, data=data)
        else:
            r = c.post(f"{API_V1}{path}", json=json)
        r.raise_for_status()
        return r.json()


def api_patch(path: str, json: dict) -> dict[str, Any]:
    with httpx.Client(timeout=30) as c:
        r = c.patch(f"{API_V1}{path}", json=json)
        r.raise_for_status()
        return r.json()


def api_delete(path: str) -> None:
    with httpx.Client(timeout=30) as c:
        r = c.delete(f"{API_V1}{path}")
        r.raise_for_status()


# ============== 侧边栏 ==============

st.sidebar.title("🚢 二掌柜订舱")
st.sidebar.caption(f"API: {API_BASE}")
page = st.sidebar.radio(
    "导航",
    [
        "📋 SO 收件箱",
        "📦 订舱管理",
        "🗺️ 运单跟踪",
        "💰 账单中心",
        "👥 订舱代理",
        "✉️ 邮件模板",
        "📜 发送历史",
        "⚙️ 系统设置",
    ],
)


# ============== 页面：SO 收件箱 ==============

if page == "📋 SO 收件箱":
    st.header("📋 SO 收件箱")

    with st.expander("📤 上传 SO（PDF / 图片）", expanded=True):
        files = st.file_uploader(
            "选择文件",
            type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp"],
            accept_multiple_files=True,
        )
        src_email = st.text_input("来源邮箱（可选）")
        src_subject = st.text_input("来源邮件主题（可选）")
        if st.button("上传并开始 OCR", type="primary") and files:
            for f in files:
                try:
                    res = api_post(
                        "/so/upload",
                        files={"file": (f.name, f.getvalue(), f.type)},
                        data={"source_email": src_email, "source_subject": src_subject},
                    )
                    st.success(f"✅ {f.name} 已上传, OCR 后台运行中...")
                except Exception as e:
                    st.error(f"❌ {f.name}: {e}")
            st.rerun()

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox("状态", ["全部", "pending", "ocr_done", "ocr_failed", "confirmed", "rejected"])
    with col2:
        carrier = st.text_input("船公司")
    with col3:
        page_size = st.number_input("每页", 5, 100, 20)

    params: dict[str, Any] = {"page": 1, "page_size": page_size}
    if status_filter != "全部":
        params["status"] = status_filter
    if carrier:
        params["carrier"] = carrier.upper()

    try:
        data = api_get("/so/", **params)
    except Exception as e:
        st.error(f"加载失败: {e}")
        st.stop()

    st.caption(f"共 {data['total']} 条")
    items = data["items"]
    if not items:
        st.info("暂无数据")
    else:
        for so in items:
            with st.container(border=True):
                cols = st.columns([3, 2, 2, 2, 1])
                with cols[0]:
                    st.markdown(f"**{so['carrier'] or '???'} {so['so_number'] or ''}**")
                    st.caption(so["file_name"])
                with cols[1]:
                    st.write(f"📍 {so['pol'] or '?'} → {so['pod'] or '?'}")
                with cols[2]:
                    st.write(f"📦 {so['container_count'] or 1} x {so['container_type'] or '?'}")
                    if so.get("etd"):
                        st.caption(f"ETD: {so['etd'][:10]}")
                with cols[3]:
                    badge = {
                        "pending": "⏳ 待 OCR",
                        "ocr_done": "✅ OCR 完成",
                        "ocr_failed": "❌ OCR 失败",
                        "confirmed": "🎯 已确认",
                        "rejected": "🚫 已拒收",
                    }.get(so["status"], so["status"])
                    st.write(badge)
                with cols[4]:
                    if st.button("详情", key=f"view_{so['id']}"):
                        st.session_state[f"show_{so['id']}"] = True

                if st.session_state.get(f"show_{so['id']}"):
                    with st.form(f"edit_{so['id']}"):
                        st.subheader(f"修正字段 - {so['file_name']}")
                        try:
                            detail = api_get(f"/so/{so['id']}")
                        except Exception as e:
                            st.error(str(e))
                            detail = None
                        if detail:
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                carrier_v = st.text_input("船公司", detail.get("carrier") or "")
                                so_no_v = st.text_input("SO 编号", detail.get("so_number") or "")
                                bl_no_v = st.text_input("BL 编号", detail.get("bl_number") or "")
                            with c2:
                                pol_v = st.text_input("POL", detail.get("pol") or "")
                                pod_v = st.text_input("POD", detail.get("pod") or "")
                                vessel_v = st.text_input("船名", detail.get("vessel_name") or "")
                            with c3:
                                container_type_v = st.text_input("柜型", detail.get("container_type") or "40HQ")
                                container_count_v = st.number_input("柜量", 0, 100, detail.get("container_count") or 1)
                                commodity_v = st.text_area("货名", detail.get("commodity") or "")

                            with st.expander("OCR 原文"):
                                st.code(detail.get("ocr_text") or "(空)")

                            cols_btn = st.columns(4)
                            with cols_btn[0]:
                                if st.form_submit_button("💾 保存修正"):
                                    try:
                                        api_patch(
                                            f"/so/{so['id']}",
                                            {
                                                "carrier": carrier_v or None,
                                                "so_number": so_no_v or None,
                                                "bl_number": bl_no_v or None,
                                                "pol": pol_v or None,
                                                "pod": pod_v or None,
                                                "vessel_name": vessel_v or None,
                                                "container_type": container_type_v or None,
                                                "container_count": int(container_count_v),
                                                "commodity": commodity_v or None,
                                            },
                                        )
                                        st.success("已保存")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[1]:
                                if st.form_submit_button("🔁 重新 OCR"):
                                    try:
                                        api_post(f"/so/{so['id']}/reocr")
                                        st.success("已加入重排")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[2]:
                                if st.form_submit_button("🎯 确认生成 Booking", type="primary"):
                                    try:
                                        api_post(f"/so/{so['id']}/confirm")
                                        st.success("已生成 Booking")
                                        st.session_state[f"show_{so['id']}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[3]:
                                if st.form_submit_button("🗑️ 删除"):
                                    try:
                                        api_delete(f"/so/{so['id']}")
                                        st.success("已删除")
                                        st.session_state[f"show_{so['id']}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))


# ============== 页面：订舱管理 ==============

elif page == "📦 订舱管理":
    st.header("📦 订舱管理")

    with st.expander("➕ 新建订舱", expanded=False):
        with st.form("new_booking"):
            c1, c2, c3 = st.columns(3)
            with c1:
                carrier = st.text_input("船公司 *", "MAERSK")
                pol = st.text_input("POL *", "CNSHA")
                pod = st.text_input("POD *", "USLAX")
            with c2:
                container_type = st.selectbox("柜型", ["20GP", "40GP", "40HQ", "45HQ", "20RF", "40RF", "20OT", "40OT"])
                container_count = st.number_input("柜量", 1, 100, 1)
                customer_name = st.text_input("客户名")
            with c3:
                customer_ref = st.text_input("客户参考号")
                weight_kg = st.number_input("重量 KG", 0.0, step=10.0)
                volume_cbm = st.number_input("体积 CBM", 0.0, step=0.1)

            try:
                agents = api_get("/agents/")
                agent_options = {f"{a['name']} ({a.get('code', '')})": a["id"] for a in agents}
            except Exception:
                agent_options = {}
            agent_label = st.selectbox("订舱代理", ["（不选）"] + list(agent_options.keys()))

            commodity = st.text_area("货物品名")
            remark = st.text_area("备注")

            if st.form_submit_button("创建", type="primary"):
                payload = {
                    "carrier": carrier,
                    "pol": pol,
                    "pod": pod,
                    "container_type": container_type,
                    "container_count": int(container_count),
                    "weight_kg": weight_kg or None,
                    "volume_cbm": volume_cbm or None,
                    "customer_name": customer_name or None,
                    "customer_ref": customer_ref or None,
                    "commodity": commodity or None,
                    "remark": remark or None,
                }
                if agent_label != "（不选）":
                    payload["agent_id"] = agent_options[agent_label]
                try:
                    res = api_post("/bookings/", json=payload)
                    st.success(f"✅ 已创建: {res['booking_no']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")

    st.divider()

    try:
        data = api_get("/bookings/", page=1, page_size=50)
    except Exception as e:
        st.error(f"加载失败: {e}")
        st.stop()

    items = data["items"]
    st.caption(f"共 {data['total']} 条")
    if items:
        df = pd.DataFrame(
            [
                {
                    "订舱号": b["booking_no"],
                    "船公司": b["carrier"],
                    "航线": f"{b['pol']}→{b['pod']}",
                    "柜型": f"{b['container_count']}x{b['container_type']}",
                    "客户": b.get("customer_name") or "-",
                    "状态": b["status"],
                    "创建": b["created_at"][:10],
                }
                for b in items
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        for b in items:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 2])
                with c1:
                    st.markdown(f"**{b['booking_no']}** · {b['carrier']}")
                    st.caption(f"{b['pol']} → {b['pod']}")
                with c2:
                    st.write(f"📦 {b['container_count']}x{b['container_type']}")
                    st.write(f"状态: {b['status']}")
                with c3:
                    if st.button("📧 发邮件", key=f"mail_{b['id']}"):
                        try:
                            res = api_post(f"/bookings/{b['id']}/send")
                            st.success(f"已发送, 状态: {res['status']}")
                        except Exception as e:
                            st.error(str(e))


# ============== 页面：订舱代理 ==============

elif page == "👥 订舱代理":
    st.header("👥 订舱代理")

    with st.expander("➕ 新增代理", expanded=False):
        with st.form("new_agent"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("代理名称 *")
                code = st.text_input("代号")
                contact_person = st.text_input("联系人")
                contact_phone = st.text_input("电话")
            with c2:
                contact_email = st.text_input("联系邮箱")
                booking_email = st.text_input("订舱收件邮箱")
                contact_wechat = st.text_input("微信")
            service_routes_str = st.text_input("擅长航线（逗号分隔）", "CNSHA-USLAX, CNNGB-NLEUR")
            cc_emails_str = st.text_input("抄送邮箱（逗号分隔）")
            notes = st.text_area("备注")

            if st.form_submit_button("创建", type="primary"):
                payload = {
                    "name": name,
                    "code": code or None,
                    "contact_person": contact_person or None,
                    "contact_phone": contact_phone or None,
                    "contact_email": contact_email or None,
                    "booking_email": booking_email or None,
                    "contact_wechat": contact_wechat or None,
                    "cc_emails": [e.strip() for e in cc_emails_str.split(",") if e.strip()],
                    "service_routes": [r.strip() for r in service_routes_str.split(",") if r.strip()],
                    "notes": notes or None,
                }
                try:
                    api_post("/agents/", json=payload)
                    st.success("已创建")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    st.divider()
    try:
        agents = api_get("/agents/")
    except Exception as e:
        st.error(str(e))
        st.stop()

    if agents:
        df = pd.DataFrame(agents)
        st.dataframe(df, use_container_width=True, hide_index=True)


# ============== 页面：邮件模板 ==============

elif page == "✉️ 邮件模板":
    st.header("✉️ 邮件模板")
    try:
        templates = api_get("/emails/templates")
    except Exception as e:
        st.error(str(e))
        st.stop()

    if templates:
        for t in templates:
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**{t['name']}** (`{t['code']}`)")
                    st.caption(f"主题: {t['subject']}")
                with c2:
                    st.write(f"启用: {'✅' if t['is_active'] else '❌'}")
                with st.expander("正文"):
                    st.code(t["body"])


# ============== 页面：发送历史 ==============

elif page == "📜 发送历史":
    st.header("📜 邮件发送历史")
    try:
        logs = api_get("/emails/logs", page=1, page_size=100)
    except Exception as e:
        st.error(str(e))
        st.stop()

    if logs:
        df = pd.DataFrame(
            [
                {
                    "时间": log["created_at"][:19],
                    "收件人": ", ".join(log["to_emails"]),
                    "主题": log["subject"],
                    "状态": log["status"],
                    "重试": log["retry_count"],
                    "错误": (log.get("error") or "")[:60],
                }
                for log in logs
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)


# ============== 页面：运单跟踪 (Kanban) ==============

elif page == "🗺️ 运单跟踪":
    st.header("🗺️ 运单跟踪看板")

    # 筛选
    cols = st.columns([2, 2, 1])
    with cols[0]:
        search = st.text_input("搜索订舱号 / 客户名")
    with cols[1]:
        carrier = st.text_input("船公司")
    with cols[2]:
        st.write("")  # spacing
        refresh = st.button("🔄 刷新", use_container_width=True)

    try:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if carrier:
            params["carrier"] = carrier.upper()
        data = api_get("/tracking/kanban", **params)
    except Exception as e:
        st.error(f"加载失败: {e}")
        st.stop()

    st.caption(f"共 {data['total']} 个订舱")
    cols = st.columns(len(data["columns"]))
    for col, column in zip(cols, data["columns"]):
        with col:
            # 颜色块
            st.markdown(
                f"### {column['label']}\n**{column['count']}**",
                help=f"status: {column['status']}",
            )
            for item in column["items"]:
                with st.container(border=True):
                    st.markdown(f"**{item['booking_no']}**")
                    st.caption(f"{item['carrier']} · {item['container']}")
                    st.caption(f"📍 {item['pol']} → {item['pod']}")
                    if item.get("customer_name"):
                        st.caption(f"👤 {item['customer_name']}")
                    if item.get("etd"):
                        st.caption(f"ETD: {item['etd'][:10]}")
                    if item.get("eta"):
                        st.caption(f"ETA: {item['eta'][:10]}")
                    if st.button("详情", key=f"kanban_view_{item['booking_id']}"):
                        st.session_state[f"kanban_booking"] = item["booking_id"]

    # 详情
    if st.session_state.get("kanban_booking"):
        bid = st.session_state["kanban_booking"]
        st.divider()
        st.subheader(f"📍 Booking 详情 & 跟踪节点")
        try:
            booking = api_get(f"/bookings/{bid}")
            status = api_get(f"/tracking/bookings/{bid}/status")
            events = api_get(f"/tracking/bookings/{bid}/events")
        except Exception as e:
            st.error(str(e))
            events = []

        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            st.markdown(f"**{booking['booking_no']}**")
            st.caption(f"{booking['carrier']} · {booking['container_count']}x{booking['container_type']}")
            st.write(f"📍 {booking['pol']} → {booking['pod']}")
        with c2:
            st.write(f"客户: {booking.get('customer_name') or '-'}")
            st.write(f"状态: **{status['current_status']}**")
        with c3:
            if st.button("关闭"):
                st.session_state["kanban_booking"] = None
                st.rerun()

        st.markdown("**📜 跟踪节点时间线**")
        for ev in events:
            with st.container(border=True):
                cs = st.columns([1, 3, 1])
                with cs[0]:
                    st.write(f"🏷️ **{ev['status']}**")
                    st.caption(ev["occurred_at"][:19])
                with cs[1]:
                    if ev.get("location"):
                        st.write(f"📍 {ev['location']}")
                    if ev.get("vessel_name"):
                        st.write(f"🚢 {ev['vessel_name']} / {ev.get('voyage_no', '')}")
                    if ev.get("container_no"):
                        st.write(f"📦 {ev['container_no']}")
                    if ev.get("remark"):
                        st.caption(f"💬 {ev['remark']}")
                with cs[2]:
                    st.caption(f"via {ev['source']}")

        st.markdown("**➕ 添加新节点**")
        with st.form("add_event"):
            c1, c2, c3 = st.columns(3)
            with c1:
                ev_status = st.selectbox(
                    "状态",
                    [
                        "booked",
                        "empty_picked_up",
                        "loaded",
                        "departed",
                        "in_transit",
                        "arrived",
                        "delivered",
                        "completed",
                        "exception",
                    ],
                )
                ev_location = st.text_input("地点")
            with c2:
                ev_vessel = st.text_input("船名")
                ev_voyage = st.text_input("航次")
                ev_container = st.text_input("柜号")
            with c3:
                ev_occurred = st.text_input("时间 (ISO)", value=datetime.now().isoformat(timespec="seconds"))
            ev_remark = st.text_area("备注")
            if st.form_submit_button("添加", type="primary"):
                try:
                    api_post(
                        f"/tracking/bookings/{bid}/events",
                        json={
                            "status": ev_status,
                            "occurred_at": ev_occurred,
                            "location": ev_location or None,
                            "vessel_name": ev_vessel or None,
                            "voyage_no": ev_voyage or None,
                            "container_no": ev_container or None,
                            "remark": ev_remark or None,
                        },
                    )
                    st.success("已添加")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


# ============== 页面：账单中心 ==============

elif page == "💰 账单中心":
    st.header("💰 账单中心")

    with st.expander("📤 上传账单（PDF / 图片）", expanded=False):
        try:
            bookings = api_get("/bookings/", page=1, page_size=100)["items"]
            booking_map = {f"{b['booking_no']} ({b['carrier']})": b["id"] for b in bookings}
        except Exception:
            booking_map = {}

        bill_files = st.file_uploader(
            "选择账单文件",
            type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp"],
            accept_multiple_files=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            bill_type = st.selectbox("账单类型", ["receivable", "payable"])
        with c2:
            booking_label = st.selectbox("关联订舱 (可选)", ["（不关联）"] + list(booking_map.keys()))

        if st.button("上传并开始 OCR", type="primary") and bill_files:
            for f in bill_files:
                try:
                    booking_id = booking_map.get(booking_label) if booking_label != "（不关联）" else None
                    res = api_post(
                        "/bills/upload",
                        files={"file": (f.name, f.getvalue(), f.type)},
                        data={"bill_type": bill_type, "booking_id": booking_id or ""},
                    )
                    st.success(f"✅ {f.name} 已上传, OCR 后台运行中...")
                except Exception as e:
                    st.error(f"❌ {f.name}: {e}")
            st.rerun()

    st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        bill_type_filter = st.selectbox("类型", ["全部", "receivable", "payable"])
    with c2:
        bill_status = st.selectbox(
            "状态",
            ["全部", "uploaded", "ocr_processing", "ocr_done", "ocr_failed", "confirmed", "disputed", "paid"],
        )
    with c3:
        bill_search = st.text_input("搜索账单号")

    params: dict[str, Any] = {"page": 1, "page_size": 30}
    if bill_type_filter != "全部":
        params["bill_type"] = bill_type_filter
    if bill_status != "全部":
        params["status"] = bill_status

    try:
        data = api_get("/bills/", **params)
    except Exception as e:
        st.error(f"加载失败: {e}")
        st.stop()

    items = data["items"]
    st.caption(f"共 {data['total']} 条")
    if bill_search:
        items = [b for b in items if bill_search.lower() in (b.get("bill_no") or "").lower()]

    if not items:
        st.info("暂无数据")
    else:
        for bill in items:
            with st.container(border=True):
                cols = st.columns([3, 2, 2, 1])
                with cols[0]:
                    st.markdown(f"**{bill['bill_no']}** ({bill['bill_kind']})")
                    st.caption(bill.get("file_name") or "无文件")
                with cols[1]:
                    st.write(f"💰 {bill['total_amount']} {bill['currency']}")
                    if bill.get("issued_at"):
                        st.caption(f"📅 {bill['issued_at'][:10]}")
                with cols[2]:
                    badge = {
                        "uploaded": "⏳ 待 OCR",
                        "ocr_processing": "🔄 OCR 中",
                        "ocr_done": "✅ OCR 完成",
                        "ocr_failed": "❌ OCR 失败",
                        "confirmed": "🎯 已确认",
                        "disputed": "⚠️ 争议",
                        "paid": "💚 已结清",
                    }.get(bill["status"], bill["status"])
                    st.write(badge)
                with cols[3]:
                    if st.button("详情", key=f"view_bill_{bill['id']}"):
                        st.session_state[f"show_bill_{bill['id']}"] = True

                if st.session_state.get(f"show_bill_{bill['id']}"):
                    try:
                        detail = api_get(f"/bills/{bill['id']}")
                    except Exception as e:
                        st.error(str(e))
                        detail = None
                    if detail:
                        with st.form(f"edit_bill_{bill['id']}"):
                            st.subheader("修正字段")
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                bill_no = st.text_input("账单号 *", detail.get("bill_no") or "")
                                seller = st.text_input("销售方", detail.get("seller_name") or "")
                                seller_tax = st.text_input("销售方税号", detail.get("seller_tax_no") or "")
                            with c2:
                                buyer = st.text_input("购买方", detail.get("buyer_name") or "")
                                buyer_tax = st.text_input("购买方税号", detail.get("buyer_tax_no") or "")
                                currency = st.text_input("币种", detail.get("currency") or "CNY")
                            with c3:
                                total = st.number_input(
                                    "价税合计",
                                    0.0,
                                    step=100.0,
                                    value=float(detail.get("total_amount") or 0),
                                )
                                tax = st.number_input(
                                    "税额",
                                    0.0,
                                    step=10.0,
                                    value=float(detail.get("tax_amount") or 0),
                                )
                                excl = st.number_input(
                                    "不含税",
                                    0.0,
                                    step=10.0,
                                    value=float(detail.get("amount_excl_tax") or 0),
                                )

                            if detail.get("line_items"):
                                with st.expander(f"明细行 ({len(detail['line_items'])} 条)"):
                                    st.json(detail["line_items"])

                            with st.expander("OCR 原文"):
                                st.code(detail.get("ocr_text") or "(空)")

                            remark = st.text_area("备注", detail.get("remark") or "")

                            cols_btn = st.columns(4)
                            with cols_btn[0]:
                                if st.form_submit_button("💾 保存", type="primary"):
                                    try:
                                        api_patch(
                                            f"/bills/{bill['id']}",
                                            {
                                                "bill_no": bill_no or detail.get("bill_no") or "PENDING",
                                                "seller_name": seller or None,
                                                "seller_tax_no": seller_tax or None,
                                                "buyer_name": buyer or None,
                                                "buyer_tax_no": buyer_tax or None,
                                                "currency": currency or "CNY",
                                                "total_amount": total or None,
                                                "tax_amount": tax or None,
                                                "amount_excl_tax": excl or None,
                                                "remark": remark or None,
                                            },
                                        )
                                        st.success("已保存")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[1]:
                                if st.form_submit_button("🔁 重新 OCR"):
                                    try:
                                        api_post(f"/bills/{bill['id']}/reocr")
                                        st.success("已加入重排")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[2]:
                                if st.form_submit_button("🎯 确认入账"):
                                    try:
                                        api_post(f"/bills/{bill['id']}/confirm")
                                        st.success("已确认")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with cols_btn[3]:
                                if st.form_submit_button("🗑️ 删除"):
                                    try:
                                        api_delete(f"/bills/{bill['id']}")
                                        st.success("已删除")
                                        st.session_state[f"show_bill_{bill['id']}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))


# ============== 页面：系统设置 ==============

elif page == "⚙️ 系统设置":
    st.header("⚙️ 系统设置")
    st.subheader("API 连接")
    st.code(f"API: {API_BASE}")
    try:
        h = httpx.get(f"{API_BASE}/health", timeout=5).json()
        st.success(f"✅ 在线 — v{h.get('version')}")
    except Exception as e:
        st.error(f"❌ 离线: {e}")

    st.subheader("SMTP 配置")
    st.caption("在 `.env` 里修改 SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD 等, 重启后端生效")

    st.subheader("OCR 引擎")
    st.caption("当前默认 PaddleOCR (中文), 首次运行会下载模型 (~100MB)")
    st.code("pip install paddleocr paddlepaddle")
