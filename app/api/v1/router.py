from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit,
    auth,
    documents,
    health,
    submissions,
    tenants,
    workflow,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(submissions.router)
api_router.include_router(documents.router)
api_router.include_router(workflow.router)
api_router.include_router(audit.router)
