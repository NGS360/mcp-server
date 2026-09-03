"""HTTP client for communicating with the NGS360 API."""

import os
from typing import Any

import httpx

from ngs360_mcp_server.auth import get_caller_authorization


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
        # Fallback credential, used only when the request carries none of its
        # own -- i.e. under stdio, where the process serves a single user.
        self.token = token or os.environ.get("NGS360_API_TOKEN", "")
        self.path_prefix = path_prefix
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        # Deliberately no Authorization here: the cached AsyncClient is shared
        # by every caller, so baking a credential in would send one user's
        # token on another user's request. Auth is resolved per request in
        # _auth_headers() and passed at call time instead.
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _auth_headers(self) -> dict[str, str]:
        """Resolve the Authorization header for the call being made.

        Prefers the caller's own header, so downstream NGS360 calls are
        attributed to the real user rather than to a shared service principal.
        Falls back to NGS360_API_TOKEN for the stdio transport. If neither is
        present the header is omitted and the API decides how to respond.
        """
        caller = get_caller_authorization()
        if caller:
            return {"Authorization": caller}
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
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
