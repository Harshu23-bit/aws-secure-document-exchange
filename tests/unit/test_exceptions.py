import json
import logging
import sys

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import JSONFormatter, request_id_context


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def http_request():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/test",
        "raw_path": b"/api/v1/test",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


@pytest.mark.anyio
async def test_unhandled_exception_does_not_expose_exception_details(
    request,
    caplog,
):
    request_id = "test-request-123"
    token = request_id_context.set(request_id)
    secret_message = "sensitive-database-connection-details"

    try:
        with caplog.at_level(logging.ERROR, logger="app.exceptions"):
            try:
                raise RuntimeError(secret_message)
            except RuntimeError as exc:
                response = await unhandled_exception_handler(http_request, exc)

        body = json.loads(response.body)

        assert response.status_code == 500
        assert body["error"]["code"] == "internal_server_error"
        assert body["error"]["message"] == "An unexpected error occurred"
        assert body["request_id"] == request_id
        assert secret_message not in response.body.decode()

        exception_records = [
            record
            for record in caplog.records
            if record.name == "app.exceptions"
        ]
        assert len(exception_records) == 1
        assert exception_records[0].exc_info is not None
    finally:
        request_id_context.reset(token)


@pytest.mark.anyio
async def test_http_500_does_not_expose_internal_details(http_request):
    request_id = "test-request-456"
    token = request_id_context.set(request_id)
    secret_message = "internal-database-error"

    try:
        exc = StarletteHTTPException(
            status_code=500,
            detail=secret_message,
        )
        response = await http_exception_handler(http_request, exc)
        body = json.loads(response.body)

        assert response.status_code == 500
        assert body["error"]["message"] == "Internal server error"
        assert body["request_id"] == request_id
        assert secret_message not in response.body.decode()
    finally:
        request_id_context.reset(token)


@pytest.mark.anyio
async def test_validation_error_does_not_expose_submitted_values(http_request):
    request_id = "test-request-789"
    token = request_id_context.set(request_id)
    secret_value = "super-secret-password"

    try:
        exc = RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body", "password"),
                    "msg": "Field required",
                    "input": secret_value,
                }
            ]
        )
        response = await validation_exception_handler(http_request, exc)
        body = json.loads(response.body)

        assert response.status_code == 422
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["message"] == "Request validation failed"
        assert body["request_id"] == request_id
        assert secret_value not in response.body.decode()
        assert body["error"]["details"][0]["location"] == ["body", "password"]
        assert body["error"]["details"][0]["type"] == "missing"
    finally:
        request_id_context.reset(token)


def test_json_formatter_includes_request_id_and_exception():
    request_id = "test-log-request-123"
    token = request_id_context.set(request_id)

    try:
        try:
            raise RuntimeError("test diagnostic exception")
        except RuntimeError:
            record = logging.LogRecord(
                name="app.exceptions",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Unhandled application exception",
                args=(),
                exc_info=sys.exc_info(),
            )

        formatted = JSONFormatter().format(record)
        log_entry = json.loads(formatted)

        assert log_entry["request_id"] == request_id
        assert log_entry["level"] == "ERROR"
        assert log_entry["logger"] == "app.exceptions"
        assert log_entry["message"] == "Unhandled application exception"
        assert "exception" in log_entry
        assert "test diagnostic exception" in log_entry["exception"]
    finally:
        request_id_context.reset(token)
