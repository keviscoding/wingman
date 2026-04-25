"""Goal presets — saveable conversation goal instructions.

Each preset is a short text instruction like "Goal is to get her on a
date this week" that gets added to the Pro prompt on top of the training.
"""

from __future__ import annotations

import json
from pathlib import Path

PRESETS_FILE = Path(__file__).parent.parent / "presets.json"


class PresetStore:
    def __init__(self):
        self._presets: list[dict] = []
        self._load()

    def _load(self):
        if PRESETS_FILE.exists():
            try:
                self._presets = json.loads(PRESETS_FILE.read_text())
            except Exception:
                self._presets = []

    def refresh(self) -> None:
        """Re-read presets.json from disk. Safe to call on every /api/state
        build: cheap (one file read), idempotent, and if the disk file is
        missing/corrupt we keep the current in-memory list rather than
        wiping it. Needed because the in-memory list can drift from disk
        (multi-process writes, import/replace operations, external edits)
        and the UI was showing the stale copy."""
        if not PRESETS_FILE.exists():
            return
        try:
            data = json.loads(PRESETS_FILE.read_text())
            if isinstance(data, list):
                self._presets = data
        except Exception:
            # Leave in-memory state alone on parse errors.
            pass

    def _save(self):
        PRESETS_FILE.write_text(json.dumps(self._presets, indent=2))

    @property
    def presets(self) -> list[dict]:
        return self._presets

    def add(self, name: str, instruction: str) -> dict:
        preset = {"name": name.strip(), "instruction": instruction.strip()}
        self._presets.append(preset)
        self._save()
        return preset

    def delete(self, index: int):
        if 0 <= index < len(self._presets):
            self._presets.pop(index)
            self._save()

    def get(self, index: int) -> str:
        if 0 <= index < len(self._presets):
            return self._presets[index]["instruction"]
        return ""

    def replace_all(self, items: list[dict]) -> None:
        """Replace goals with validated {name, instruction} dicts (import from JSON)."""
        out: list[dict] = []
        for p in items:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            instr = str(p.get("instruction", "")).strip()
            if name and instr:
                out.append({"name": name, "instruction": instr})
        self._presets = out
        self._save()
