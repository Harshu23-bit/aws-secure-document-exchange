import logging
import time
from uuid import uuid4

from app.core.logging import request_id_context

logger = logging.getLogger("app.request")


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        context_token = request_id_context.set(request_id)

        start_time = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message):
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

                headers = list(message.get("headers", []))
                headers.append(
                    (
                        b"x-request-id",
                        request_id.encode("ascii"),
                    )
                )

                message["headers"] = headers

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)

        finally:
            duration_ms = round(
                (time.perf_counter() - start_time) * 1000,
                2,
            )

            logger.info(
                "HTTP request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )

            request_id_context.reset(context_token)
