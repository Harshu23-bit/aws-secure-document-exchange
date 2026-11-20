from uuid import UUID

import pytest
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import validation_exception_handler
from app.main import app
from app.middleware.request_context import RequestContextMiddleware


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def client():
    transport = ASGITransport(app=app)

    return AsyncClient(
        transport=transport,
        base_url="http://test",
    )


@pytest.mark.anyio
async def test_root_endpoint(client):
    async with client as test_client:
        response = await test_client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Secure Document Exchange API",
        "version": "0.1.0",
        "documentation": "/docs",
    }


@pytest.mark.anyio
async def test_root_health_endpoint(client):
    async with client as test_client:
        response = await test_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.anyio
async def test_versioned_health_endpoint(client):
    async with client as test_client:
        response = await test_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "document-exchange-api",
    }


@pytest.mark.anyio
async def test_openapi_documentation(client):
    async with client as test_client:
        response = await test_client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == (
        "Secure Multi-Tenant Document Exchange Platform"
    )


@pytest.mark.anyio
async def test_request_id_is_generated(client):
    async with client as test_client:
        response = await test_client.get("/health")

    request_id = response.headers["X-Request-ID"]

    UUID(request_id)


@pytest.mark.anyio
async def test_client_cannot_choose_request_id(client):
    async with client as test_client:
        response = await test_client.get(
            "/health",
            headers={"X-Request-ID": "attacker-controlled-value"},
        )

    assert response.headers["X-Request-ID"] != ("attacker-controlled-value")

    UUID(response.headers["X-Request-ID"])


@pytest.mark.anyio
async def test_not_found_error_format(client):
    async with client as test_client:
        response = await test_client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["message"] == "Not Found"
    assert "request_id" in response.json()


@pytest.mark.anyio
async def test_validation_error_format():
    test_app = FastAPI()

    test_app.add_middleware(RequestContextMiddleware)

    test_app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )

    @test_app.get("/validate")
    async def validate_document(
        document_id: int = Query(...),
    ):
        return {"document_id": document_id}

    transport = ASGITransport(app=test_app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as test_client:
        response = await test_client.get("/validate")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"] == ("Request validation failed")
    assert "request_id" in response.json()
    assert "input" not in str(response.json())
