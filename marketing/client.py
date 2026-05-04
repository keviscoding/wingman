"""Self-contained Gemini client with key rotation.

Extracted from the main wingman codebase so the ``marketing`` package
can live in its own repository (``muzochatgen``) without pulling in the
full Muzo backend.

Behavior matches the upstream helper:

* ``GEMINI_API_KEYS=key1,key2,key3`` in env — comma-separated pool.
  ``GEMINI_API_KEY=keyX`` is supported as a single-key fallback.
* ``make_genai_client()`` returns a genai.Client bound to the current
  pool index.
* ``rotate_api_key()`` cycles to the next key on rate-limit errors.

Vertex AI mode is intentionally NOT supported here — the marketing
tool is a standalone service that should just hit AI Studio directly.
If we ever want Vertex for this we can add it back.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google import genai as _genai_typing  # noqa: F401


PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview").strip()
FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview").strip()


_ALL_KEYS: list[str] = [
    k.strip()
    for k in os.getenv(
        "GEMINI_API_KEYS",
        os.getenv("GEMINI_API_KEY", ""),
    ).split(",")
    if k.strip()
]
_key_index = 0


def make_genai_client():
    """Create a genai.Client using the current key from the pool.

    Raises ``RuntimeError`` if no keys are configured — much better to
    fail fast on boot than to surface a cryptic HTTP error later.
    """
    from google import genai as _genai

    if not _ALL_KEYS:
        raise RuntimeError(
            "No Gemini API keys configured. Set GEMINI_API_KEYS "
            "(comma-separated) or GEMINI_API_KEY in env."
        )
    key = _ALL_KEYS[_key_index % len(_ALL_KEYS)]
    return _genai.Client(api_key=key)


def rotate_api_key() -> None:
    """Advance to the next key in the pool. No-op if only one key.

    Call after a 429 or auth error — our retry loop does this so
    a hot-throttled key doesn't blow up the whole generation queue.
    """
    global _key_index
    if not _ALL_KEYS:
        return
    _key_index = (_key_index + 1) % len(_ALL_KEYS)
