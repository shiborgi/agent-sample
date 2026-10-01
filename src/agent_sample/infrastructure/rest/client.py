"""Cliente REST com as regras do projeto.

- só fala com hosts permitidos por configuração;
- a credencial vem do ambiente e nunca aparece em log, erro ou caminho da revisão;
- tempo limite em toda chamada;
- novas tentativas limitadas, só em erros transitórios;
- erros traduzidos para mensagens claras.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from agent_sample.domain.model import ChangeNotFound, RemoteError

logger = logging.getLogger(__name__)

TRANSIENT = frozenset({429, 502, 503, 504})


class RestClient:
    def __init__(
        self,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        token: str | None,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        backoff: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._allowed = allowed_hosts
        self._token = token
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._transport = transport
        self._sleep = sleep
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._closed = False

    async def aclose(self) -> None:
        """Libera o pool. Chamado pela composição no final do processo."""
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def request(
        self,
        method: str,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = httpx.URL(f"{self._base_url}{path}")
        if url.host not in self._allowed:
            raise RemoteError(f"host not allowed: {url.host} (allowed: {', '.join(self._allowed)})")
        headers = {"Accept": accept, "User-Agent": "agent-sample-reviewer"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        client = self._client
        # Se o pool já foi fechado, abre um cliente descartável (recuperável).
        if self._closed:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as opened:
                return await self._request_with(opened, method, url, path, headers, json)
        return await self._request_with(client, method, url, path, headers, json)

    async def _request_with(self, client, method, url, path, headers, json):
        for attempt in range(self._retries + 1):
            last = attempt == self._retries
            try:
                response = await client.request(method, url, headers=headers, json=json)
            except httpx.TransportError as exc:
                if last:
                    raise RemoteError(f"{method} {url.host}{path}: {type(exc).__name__}") from None
                await self._retry(method, path, type(exc).__name__, attempt)
                continue
            if response.status_code in TRANSIENT and not last:
                await self._retry(method, path, f"HTTP {response.status_code}", attempt)
                continue
            return _checked(method, path, response)
        raise RemoteError(f"{method} {path}: no response")  # pragma: no cover - laço sempre retorna

    async def _retry(self, method: str, path: str, reason: str, attempt: int) -> None:
        logger.warning("%s %s failed (%s); retrying", method, path, reason)
        await self._sleep(self._backoff * 2**attempt)


def _checked(method: str, path: str, response: httpx.Response) -> httpx.Response:
    status = response.status_code
    if status < 400:
        return response
    if status == 401:
        raise RemoteError("authentication failed (HTTP 401): check the token in the environment")
    if status == 403:
        raise RemoteError(f"access denied (HTTP 403) for {method} {path}")
    if status == 404:
        raise ChangeNotFound(f"{path} (HTTP 404)")
    raise RemoteError(f"{method} {path} failed with HTTP {status}")
