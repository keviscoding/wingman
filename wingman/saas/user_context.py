"""Per-user data isolation.

Every user gets their own filesystem root under ``data/users/<user_id>/``.
We mirror the same directory layout the personal-mode app uses so the
existing storage classes (ChatStore, ExampleStore, CaseStudyStore,
GlobalSettings) can be pointed at a user-specific root without code
changes — they just take a different base path.

This is the abstraction that makes the SaaS side multi-tenant without
forking the generation pipeline. The pipeline still does:

    chats = wingman.chat_store.load(contact)

…it just operates on a UserContext-bound store rather than the global one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


USERS_ROOT = Path("data/users")


@dataclass
class UserContext:
    user_id: str
    plan: str = "free"

    @property
    def root(self) -> Path:
        p = USERS_ROOT / self.user_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def chats_dir(self) -> Path:
        p = self.root / "chats"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def case_studies_dir(self) -> Path:
        p = self.root / "case_studies"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def examples_dir(self) -> Path:
        p = self.root / "examples_library"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def settings_path(self) -> Path:
        return self.root / "global_settings.json"

    def get_settings(self) -> dict:
        if not self.settings_path.exists():
            return {}
        try:
            return json.loads(self.settings_path.read_text())
        except Exception:
            return {}

    def save_settings(self, data: dict) -> None:
        self.settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_context(user_id: str, plan: str = "free") -> UserContext:
    return UserContext(user_id=user_id, plan=plan)
