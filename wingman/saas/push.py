"""Server-side push notifications via the Expo Push API.

Fires when a generation completes, so the user's phone "dings" even
when the app is suspended in background — JS execution doesn't have
to be alive on the device. This is the same pattern WhatsApp /
Instagram use (server pushes via FCM/APNs).

We use Expo's hosted Push service: it abstracts FCM (Android) +
APNs (iOS) behind a single HTTP endpoint and uses tokens that look
like ``ExponentPushToken[...]``. Free, zero setup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
log = logging.getLogger("wingman.push")


async def send_expo_push(
    token: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Fire a single push notification via Expo. Best-effort: logs and
    swallows errors so a flaky push service can never break a successful
    generation response."""
    if not token or not token.startswith("ExponentPushToken"):
        return
    payload = {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "priority": "high",
        "channelId": "default",
        "data": data or {},
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(EXPO_PUSH_URL, json=payload)
            if r.status_code >= 400:
                log.warning("expo push failed (%s): %s", r.status_code, r.text[:200])
    except Exception as exc:
        log.warning("expo push error: %s", exc)


def fire_and_forget(token: str, title: str, body: str, data: dict[str, Any] | None = None) -> None:
    """Schedule send_expo_push without awaiting it. Useful when the
    caller is on a hot path (e.g. inside the quick-capture route that
    needs to return JSON to the mobile app fast)."""
    if not token:
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(send_expo_push(token, title, body, data))
    except Exception as exc:
        log.warning("failed to schedule push: %s", exc)
