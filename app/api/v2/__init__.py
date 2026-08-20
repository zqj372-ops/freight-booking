"""API v2 - v0.5 core workflow 主用路由"""

from fastapi import APIRouter

from app.api.v2 import (
    organization,
    partner,
    audit_log,
    shipment,
    booking_request,
    booking_confirmation,
    container,
)

api_router = APIRouter()
api_router.include_router(organization.router, prefix="/organizations", tags=["组织"])
api_router.include_router(partner.router, prefix="/partners", tags=["合作方"])
api_router.include_router(audit_log.router, prefix="/audit-logs", tags=["审计日志"])
api_router.include_router(shipment.router, prefix="/shipments", tags=["业务单"])
api_router.include_router(booking_request.router, prefix="/booking-requests", tags=["订舱申请"])
api_router.include_router(booking_confirmation.router, prefix="/booking-confirmations", tags=["订舱确认"])
api_router.include_router(container.router, prefix="/containers", tags=["柜"])
