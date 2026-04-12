"""Catalog state and dedupe ledger helpers."""

from __future__ import annotations

import json
from pathlib import Path

from .models import CatalogLedger, DedupeRecord
from .utils import pretty_json


class CatalogStateStore:
    """Persist ledger state for repeatable catalog runs."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._ledger_path = self._root_dir / "index.json"
        self._ledger_cache: CatalogLedger | None = None

    def load_ledger(self, *, force_reload: bool = False) -> CatalogLedger:
        """Load the current dedupe ledger."""
        if self._ledger_cache is not None and not force_reload:
            return self._ledger_cache
        if not self._ledger_path.exists():
            self._ledger_cache = CatalogLedger()
            return self._ledger_cache
        payload = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            self._ledger_cache = CatalogLedger()
            return self._ledger_cache
        self._ledger_cache = CatalogLedger.from_dict(payload)
        return self._ledger_cache

    def save_ledger(self, ledger: CatalogLedger) -> None:
        """Write the dedupe ledger to disk."""
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path.write_text(
            pretty_json(ledger.to_dict()),
            encoding="utf-8",
        )
        self._ledger_cache = ledger

    def contains(self, dedupe_key: str) -> bool:
        """Return whether the dedupe ledger already contains one key."""
        ledger = self.load_ledger()
        return any(record.dedupe_key == dedupe_key for record in ledger.records)

    def append(self, record: DedupeRecord) -> None:
        """Append one dedupe record when it is not already present."""
        ledger = self.load_ledger()
        if any(item.dedupe_key == record.dedupe_key for item in ledger.records):
            return
        ledger.records.append(record)
        self.save_ledger(ledger)
