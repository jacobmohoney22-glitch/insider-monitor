from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta

from .form4 import Purchase

SEEN_TTL_DAYS = 30
ALERT_TTL_DAYS = 45


class State:
    """Everything the bot remembers between runs (so nothing is alerted twice)."""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.started: str | None = d.get("started")
        self.seen: dict[str, str] = dict(d.get("seen", {}))          # accession -> iso ts
        self.alerted: dict[str, str] = dict(d.get("alerted", {}))    # alert key -> iso ts
        self.purchases: dict[str, dict] = dict(d.get("purchases", {}))  # uid -> purchase

    @property
    def is_new(self) -> bool:
        return not self.started

    # --- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "State":
        if not os.path.exists(path):
            return cls()
        try:
            with open(path) as f:
                return cls(json.load(f))
        except json.JSONDecodeError as e:
            # refuse to silently reset: that would re-alert on old filings
            raise SystemExit(f"State file {path} is corrupt ({e}). "
                             "Delete it deliberately to start fresh.")

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump({"started": self.started, "seen": self.seen,
                       "alerted": self.alerted, "purchases": self.purchases},
                      f, indent=1, sort_keys=True)
        os.replace(tmp, path)   # atomic: never leaves a half-written file

    # --- mutation ----------------------------------------------------------
    def mark_seen(self, accession: str, now: datetime) -> None:
        self.seen[accession] = now.isoformat()

    def add_purchases(self, purchases: list[Purchase]) -> int:
        added = 0
        for p in purchases:
            if p.uid not in self.purchases:
                added += 1
            self.purchases[p.uid] = asdict(p)
        return added

    def mark_alerted(self, key: str, now: datetime) -> None:
        self.alerted[key] = now.isoformat()

    def all_purchases(self) -> list[Purchase]:
        return [Purchase(**d) for d in self.purchases.values()]

    def prune(self, now: datetime, window_days: int) -> None:
        def older(ts: str, days: int) -> bool:
            return datetime.fromisoformat(ts) < now - timedelta(days=days)
        self.seen = {k: v for k, v in self.seen.items() if not older(v, SEEN_TTL_DAYS)}
        self.alerted = {k: v for k, v in self.alerted.items() if not older(v, ALERT_TTL_DAYS)}
        cutoff = (now - timedelta(days=window_days + 7)).date().isoformat()
        self.purchases = {k: v for k, v in self.purchases.items() if v["tx_date"] >= cutoff}
