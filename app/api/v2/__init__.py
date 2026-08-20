"""API v2 - v0.5 core workflow 主用路由"""

from fastapi import APIRouter

from app.api.v2 import organization, partner, audit_log

api_router = APIRouter()
api_router.include_router(organization.router, prefix="/organizations", tags=["组织"])
api_router.include_router(partner.router, prefix="/partners", tags=["合作方"])
api_router.include_router(audit_log.router, prefix="/audit-logs", tags=["审计日志"])
