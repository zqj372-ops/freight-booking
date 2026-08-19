"""API v1 聚合路由"""

from fastapi import APIRouter

from app.api.v1 import so, booking, agent, email, bill, tracking, imap, finance

api_router = APIRouter()
api_router.include_router(so.router, prefix="/so", tags=["SO 收件箱"])
api_router.include_router(booking.router, prefix="/bookings", tags=["订舱"])
api_router.include_router(agent.router, prefix="/agents", tags=["订舱代理"])
api_router.include_router(email.router, prefix="/emails", tags=["邮件"])
api_router.include_router(bill.router, prefix="/bills", tags=["账单"])
api_router.include_router(tracking.router, prefix="/tracking", tags=["运单跟踪"])
api_router.include_router(imap.router, prefix="/imap", tags=["IMAP 自动拉取"])
api_router.include_router(finance.router, prefix="/finance", tags=["财务"])
