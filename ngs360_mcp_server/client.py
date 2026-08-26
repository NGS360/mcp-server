"""HTTP client for communicating with the NGS360 API.

Auth is resolved **per request**, not at construction. The server runs stateless
behind a load balancer and one client instance serves concurrent callers, so the
credential cannot be baked into a shared httpx.AsyncClient.

Resolution order for every call:

1. The ``Authorization`` header on the inbound MCP request, when there is one.
   This is how a caller acts as a specific NGS360 user — the agent forwards the
   logged-in user's bearer token and the API's own per-user authorization decides
   what the call may do.
2. ``NGS360_API_TOKEN`` from the environment. Used by the stdio transport, which
   has no inbound HTTP request at all.
3. Nothing. No ``Authorization`` header is sent and the API answers as it does
   for any unauthenticated caller.
"""

import os
from typing import Any

import httpx


def _inbound_authorization() -> str | None:
    """Return the Authorization header of the MCP request being handled.

    None when there is no inbound HTTP request — the stdio transport, direct
    in-process use, or a call made outside a request handler. The MCP request
    context is a ContextVar set per request, so this is safe under concurrency.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except (ImportError, LookupError, AttributeError):
        return None

    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return headers.get("authorization") or None


class NGS360Client:
    """HTTP client wrapper for the NGS360 REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        path_prefix: str = "/api/v1",
    ):
        self.base_url = (
            base_url or os.environ.get("NGS360_API_URL", "http://localhost:8000")
        ).rstrip("/")
        # Fallback credential only — see the module docstring. Read lazily in
        # _auth_headers so the env can be set after construction.
        self.token = token
        self.path_prefix = path_prefix
        self._client: httpx.AsyncClient | None = None

    def _auth_headers(self) -> dict[str, str]:
        """Build the per-request auth headers. May be empty."""
        inbound = _inbound_authorization()
        if inbound:
            return {"Authorization": inbound}

        token = (
            self.token
            if self.token is not None
            else os.environ.get("NGS360_API_TOKEN", "")
        )
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    async def _get_client(self) -> httpx.AsyncClient:
        # Deliberately no auth here: the client is shared across callers, so
        # credentials are passed per call instead.
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=60.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.get(
            f"{self.path_prefix}{path}", params=params, headers=self._auth_headers()
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def post(
        self,
        path: str,
        json: dict[str, Any] | list | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.post(
            f"{self.path_prefix}{path}",
            json=json,
            data=data,
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.put(
            f"{self.path_prefix}{path}",
            json=json,
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def patch(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.patch(
            f"{self.path_prefix}{path}", json=json, headers=self._auth_headers()
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict | str | None:
        client = await self._get_client()
        resp = await client.delete(
            f"{self.path_prefix}{path}", params=params, headers=self._auth_headers()
        )
        resp.raise_for_status()
        if resp.status_code == 204:
            return None
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text
