import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.core.config import Settings


def run_lifespan(application):
    async def execute():
        async with application.router.lifespan_context(application):
            pass

    return asyncio.run(execute())


def valid_production_settings(**overrides):
    values = {
        "environment": "production",
        "debug": False,
        "cognito_region": "ap-south-1",
        "cognito_user_pool_id": "ap-south-1_AbCdEf123",
        "cognito_api_client_id": "testclient123",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_startup_rejects_missing_cognito():
    application = main.create_app(Settings(environment="production"))

    with pytest.raises(ValueError, match="Cognito configuration is incomplete"):
        run_lifespan(application)


def test_production_startup_rejects_debug_mode():
    application = main.create_app(valid_production_settings(debug=True))

    with pytest.raises(RuntimeError, match="Debug mode"):
        run_lifespan(application)


def test_production_startup_accepts_valid_configuration():
    application = main.create_app(valid_production_settings())

    run_lifespan(application)


def test_development_startup_allows_missing_cognito():
    application = main.create_app(Settings(environment="development"))

    run_lifespan(application)


@pytest.mark.anyio
async def test_production_disables_api_documentation():
    application = main.create_app(valid_production_settings())
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs_response = await client.get("/docs")
        redoc_response = await client.get("/redoc")
        openapi_response = await client.get("/openapi.json")
        health_response = await client.get("/health")
        root_response = await client.get("/")

    assert docs_response.status_code == 404
    assert redoc_response.status_code == 404
    assert openapi_response.status_code == 404

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "healthy"

    assert root_response.status_code == 200
    assert "documentation" not in root_response.json()


@pytest.mark.anyio
async def test_development_keeps_api_documentation_enabled():
    application = main.create_app(Settings(environment="development"))
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs_response = await client.get("/docs")
        redoc_response = await client.get("/redoc")
        openapi_response = await client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200
    assert openapi_response.status_code == 200
