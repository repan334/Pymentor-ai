from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


async def _reject(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    code: str,
    max_bytes: int,
) -> None:
    response = JSONResponse(
        status_code=413,
        content={
            "detail": {
                "code": code,
                "message": f"Request body exceeds the {max_bytes} byte limit",
            }
        },
    )
    await response(scope, receive, send)


async def _read_body(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    max_bytes: int,
    code: str,
) -> Receive | None:
    """Buffer an HTTP body up to max_bytes; reject with 413 when it grows larger."""
    content_length = dict(scope.get("headers", [])).get(b"content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                await _reject(scope, receive, send, code=code, max_bytes=max_bytes)
                return None
        except ValueError:
            pass

    received = 0
    messages: list[Message] = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > max_bytes:
                await _reject(scope, receive, send, code=code, max_bytes=max_bytes)
                return None
            if not message.get("more_body", False):
                break
        elif message["type"] == "http.disconnect":
            return None

    message_index = 0

    async def replay_receive() -> Message:
        nonlocal message_index
        if message_index < len(messages):
            message = messages[message_index]
            message_index += 1
            return message
        return {"type": "http.request", "body": b"", "more_body": False}

    return replay_receive


class MultipartBodyLimitMiddleware:
    """Enforce an actual ASGI body-byte limit on the ingestion route."""

    def __init__(self, app: ASGIApp, *, path: str, max_bytes: int) -> None:
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return

        replay_receive = await _read_body(
            scope,
            receive,
            send,
            max_bytes=self.max_bytes,
            code="multipart_body_too_large",
        )
        if replay_receive is not None:
            await self.app(scope, replay_receive, send)


class JsonBodyLimitMiddleware:
    """Enforce an actual ASGI body-byte limit on JSON mutation routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        exclude_paths: tuple[str, ...],
        max_bytes: int,
    ) -> None:
        self.app = app
        self.exclude_paths = exclude_paths
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PUT"}
            or scope["path"] in self.exclude_paths
        ):
            await self.app(scope, receive, send)
            return

        replay_receive = await _read_body(
            scope,
            receive,
            send,
            max_bytes=self.max_bytes,
            code="json_body_too_large",
        )
        if replay_receive is not None:
            await self.app(scope, replay_receive, send)
