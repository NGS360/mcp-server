"""HTTP client for communicating with the GA4GH Workflow Execution Service (WES) API."""

import os
from typing import Any

import httpx


class WESClient:
    """HTTP client wrapper for the GA4GH WES REST API.

    This service runs on a separate host from the NGS360 API.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ):
        self.base_url = (
            base_url or os.environ.get("WES_API_URL", "http://localhost:8080")
        ).rstrip("/")
        self.token = token or os.environ.get("WES_API_TOKEN", "")
        self._client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
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
        resp = await client.get(f"/ga4gh/wes/v1{path}", params=params)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict | list | str:
        client = await self._get_client()
        resp = await client.post(
            f"/ga4gh/wes/v1{path}", json=json, data=data, params=params
        )
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text
