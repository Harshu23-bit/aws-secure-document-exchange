class ApiGatewayStagePrefixMiddleware:
    def __init__(self, app, prefix: str = ""):
        self.app = app
        self.prefix = prefix.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.prefix:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        raw_path = scope.get("raw_path", b"")
        prefix_bytes = self.prefix.encode("ascii")

        if path == self.prefix or path.startswith(self.prefix + "/"):
            updated_scope = dict(scope)
            updated_scope["path"] = path[len(self.prefix) :] or "/"

            if raw_path.startswith(prefix_bytes):
                updated_scope["raw_path"] = raw_path[len(prefix_bytes) :] or b"/"

            await self.app(updated_scope, receive, send)
            return

        await self.app(scope, receive, send)
