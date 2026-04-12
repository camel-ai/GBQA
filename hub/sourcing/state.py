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

    def load_ledger(self) -> CatalogLedger:
        """Load the current dedupe ledger."""
        if not self._ledger_path.exists():
            return CatalogLedger()
        payload = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return CatalogLedger()
        return CatalogLedger.from_dict(payload)

    def save_ledger(self, ledger: CatalogLedger) -> None:
        """Write the dedupe ledger to disk."""
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path.write_text(
            pretty_json(ledger.to_dict()),
            encoding="utf-8",
        )

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
