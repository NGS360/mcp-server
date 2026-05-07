"""HTTP client for communicating with the NGS360 API."""

import os
from typing import Any

import httpx


class NGS360Client:
    """HTTP client wrapper for the NGS360 REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ):
        self.base_url = (
            base_url or os.environ.get("NGS360_API_URL", "http://localhost:8000")
        ).rstrip("/")
        self.token = token or os.environ.get("NGS360_API_TOKEN", "")
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

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
        resp = await client.get(f"/api/v1{path}", params=params)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def post(
        self,
        path: str,
        json: dict[str, Any] | list | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.post(f"/api/v1{path}", json=json, params=params)
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
        resp = await client.put(f"/api/v1{path}", json=json, params=params)
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
        resp = await client.patch(f"/api/v1{path}", json=json)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict | str | None:
        client = await self._get_client()
        resp = await client.delete(f"/api/v1{path}", params=params)
        resp.raise_for_status()
        if resp.status_code == 204:
            return None
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text
