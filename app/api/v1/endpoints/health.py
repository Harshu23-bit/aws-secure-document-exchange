from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Application health check")
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "document-exchange-api",
    }
