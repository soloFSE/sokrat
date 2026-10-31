"""Минимальный клиент Bot API мессенджера MAX (dev.max.ru/docs-api)."""
import logging

import httpx

from .config import BOT_TOKEN, MAX_API_URL
from .http import ssl_context

log = logging.getLogger("max")


class MaxApi:
    def __init__(self, token: str = BOT_TOKEN, base_url: str = MAX_API_URL):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": token},
            timeout=httpx.Timeout(40.0, connect=10.0),
            verify=ssl_context(),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = await self.client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            log.warning("MAX API %s %s -> %s %s", method, path, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def me(self) -> dict:
        return await self._request("GET", "/me")

    async def get_updates(self, marker: int | None, timeout: int = 30) -> dict:
        params = {"timeout": timeout, "limit": 100}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str,
        buttons: list[list[dict]] | None = None,
        fmt: str | None = "markdown",
    ) -> dict:
        params = {"user_id": user_id} if user_id else {"chat_id": chat_id}
        body: dict = {"text": text}
        if fmt:
            body["format"] = fmt
        if buttons:
            body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
        return await self._request("POST", "/messages", params=params, json=body)

    async def answer_callback(self, callback_id: str, notification: str) -> dict:
        return await self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json={"notification": notification}
        )

    async def subscribe_webhook(self, url: str) -> dict:
        return await self._request(
            "POST",
            "/subscriptions",
            json={"url": url, "update_types": ["bot_started", "message_created", "message_callback"]},
        )
