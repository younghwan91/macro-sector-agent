"""텔레그램 봇 전송 — `fin-checkup` 에서 벤더링 (`docs/08-data-contract.md` §5).

출처: https://github.com/younghwan91/fin-checkup
파일: src/fin_checkup/alerts/telegram.py
커밋: df47aeecf9c1680e9989ae88cb493c68688ea08b
복사: 2026-08-23 (M8).

원본에서 바꾼 것:
- 설정을 `.env` 의 `TELEGRAM_BOT_TOKEN` 이 아니라 환경변수 `MSA_TELEGRAM_TOKEN` ·
  `MSA_TELEGRAM_CHAT_ID` 에서 읽는다 (`telegram_config()`). **둘 다 있어야** 보낸다 —
  없으면 `None` 을 돌려주고 호출자는 "not configured" 로 보고한다. 조용히 건너뛰지 않는다.
- `get_updates` · `me` (롱폴링 봇용) 는 운영 계층이 쓰지 않아 뺐다. `send` 본문은 원본 그대로.
- 동기 호출자(`msa check`)를 위해 `send_sync` 래퍼를 더했다.
- mypy strict 에 맞춰 타입을 보강했다 (`dict` → `dict[str, Any]`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

ENV_TOKEN = "MSA_TELEGRAM_TOKEN"
ENV_CHAT_ID = "MSA_TELEGRAM_CHAT_ID"


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    chat_id: str


def telegram_config() -> TelegramConfig | None:
    """환경변수 둘 다 있으면 설정, 하나라도 없으면 None (= not configured)."""
    token = os.environ.get(ENV_TOKEN, "").strip()
    chat = os.environ.get(ENV_CHAT_ID, "").strip()
    if not token or not chat:
        return None
    return TelegramConfig(token=token, chat_id=chat)


class Notifier(Protocol):
    """알림 채널. 텔레그램 외에 카카오 등을 붙일 때 이 모양을 지킨다."""

    async def send(self, chat_id: str, text: str) -> bool: ...


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not bot_token.strip():
            raise ValueError(
                "텔레그램 봇 토큰이 없습니다. @BotFather에서 발급받아 "
                f"환경변수 {ENV_TOKEN} 에 넣어주세요."
            )
        self.bot_token = bot_token
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def __aenter__(self) -> TelegramNotifier:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(self, chat_id: str, text: str) -> bool:
        """보냈으면 True. 실패해도 예외를 올리지 않는다 — 알림 하나 때문에
        워커 전체가 멈추면 나머지 종목의 공시를 놓친다."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = await self._client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except httpx.HTTPError:
            logger.exception("[telegram] 전송 실패 chat_id=%s", chat_id)
            return False

        if resp.status_code != 200:
            logger.error(
                "[telegram] 전송 거절 chat_id=%s status=%s body=%s",
                chat_id,
                resp.status_code,
                resp.text[:200],
            )
            return False
        return bool(resp.json().get("ok"))

    def send_sync(self, chat_id: str, text: str) -> bool:
        """동기 호출자용. 이벤트 루프가 이미 돌고 있는 컨텍스트에서는 `send` 를 await 해라."""

        async def _run() -> bool:
            async with self:
                return await self.send(chat_id, text)

        return asyncio.run(_run())


class ConsoleNotifier:
    """토큰 없이 워커를 돌려볼 때 쓰는 채널. 터미널에 찍기만 한다."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id: str, text: str) -> bool:
        self.sent.append((chat_id, text))
        print(f"\n─── to {chat_id} ───\n{text}\n")
        return True
