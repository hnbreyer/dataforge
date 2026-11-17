"""Bound HTTP request bodies before multipart or JSON decoding allocates memory."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_file_bytes: int):
        self.app = app
        self.max_file_bytes = max_file_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        limit = (
            self.max_file_bytes + 65536
            if scope["path"] in {"/import", "/api/v1/imports"}
            else 1_000_000
        )
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        if declared < 0 or declared > limit:
            await JSONResponse({"detail": "Request body exceeds size limit"}, status_code=413)(
                scope, receive, send
            )
            return
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                await JSONResponse({"detail": "Request body exceeds size limit"}, status_code=413)(
                    scope, receive, send
                )
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
