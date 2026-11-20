from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.middleware.api_gateway_stage import ApiGatewayStagePrefixMiddleware
from app.middleware.request_context import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level)


def create_app(app_settings: Settings) -> FastAPI:
    docs_enabled = app_settings.environment.strip().lower() in {
        "development",
        "test",
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if app_settings.environment.strip().lower() == "production":
            app_settings.validate_cognito_configuration()
            if app_settings.debug:
                raise RuntimeError("Debug mode must be disabled in production")

        yield

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=(
            "A secure multi-tenant platform for vendor document "
            "submission, review, and approval workflows."
        ),
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=[
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
        ],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    application.add_middleware(
        ApiGatewayStagePrefixMiddleware,
        prefix=app_settings.api_gateway_stage_prefix,
    )

    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    application.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )

    application.include_router(api_router, prefix="/api/v1")

    @application.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        response = {
            "message": "Secure Document Exchange API",
            "version": app_settings.app_version,
        }
        if docs_enabled:
            response["documentation"] = "/docs"
        return response

    @application.get("/health", tags=["Health"])
    async def root_health() -> dict[str, str]:
        return {
            "status": "healthy",
            "environment": app_settings.environment,
        }

    return application


app = create_app(settings)
