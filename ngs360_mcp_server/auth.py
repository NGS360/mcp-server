"""Per-request caller credentials for the streamable-HTTP transport.

Over stdio the server is a single-user process, so reading one NGS360_API_TOKEN
from the environment is correct. Hosted over HTTP it serves many users at once,
and a single shared service token would attribute every downstream NGS360 call
to one principal -- losing per-user attribution and whatever per-user
authorization the API applies.

So the caller's own Authorization header is captured per request here and read
back by NGS360Client when it builds a downstream request. A ContextVar is used
rather than threading a token through every tool signature: tools capture their
NGS360Client in a closure at registration time, and there are ~75 of them.
"""

import contextvars
from collections.abc import Awaitable, Callable
from typing import Any

# Set for the duration of one HTTP request; None under stdio, or when the
# caller sent no Authorization header.
_caller_authorization: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "caller_authorization", default=None
)

ASGIApp = Callable[[dict[str, Any], Callable[..., Any], Callable[..., Any]], Awaitable[None]]


def get_caller_authorization() -> str | None:
    """Return the Authorization header of the request being handled, if any."""
    return _caller_authorization.get()


def forward_caller_authorization(app: ASGIApp) -> ASGIApp:
    """Wrap an ASGI app so each request's Authorization header is visible to
    NGS360Client for the duration of that request.

    Non-HTTP scopes (notably "lifespan") are passed straight through, which is
    what keeps the StreamableHTTP session manager's startup/shutdown working.
    """

    async def middleware(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        header: str | None = None
        # ASGI guarantees header names are lower-cased bytes.
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value.decode("latin-1")
                break

        token = _caller_authorization.set(header)
        try:
            await app(scope, receive, send)
        finally:
            _caller_authorization.reset(token)

    return middleware
