from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from .config import Config
from .form4 import Purchase


@dataclass(frozen=True)
class Cluster:
    key: str                  # changes when a new insider joins -> fresh alert
    issuer_cik: str
    ticker: str
    issuer_name: str
    purchases: tuple[Purchase, ...]
    insider_count: int
    total_value: float
    first_date: str
    last_date: str


def _eligible(p: Purchase, cfg: Config, today: date) -> bool:
    if p.price is not None and p.price < cfg.min_price:
        return False
    return date.fromisoformat(p.tx_date) >= today - timedelta(days=cfg.window_days)


def find_clusters(purchases: Iterable[Purchase], cfg: Config, today: date) -> list[Cluster]:
    """Companies where >= min_insiders DISTINCT insiders bought inside the window
    and the combined value is >= min_cluster_value."""
    by_issuer: dict[str, list[Purchase]] = {}
    for p in purchases:
        if _eligible(p, cfg, today):
            by_issuer.setdefault(p.issuer_cik, []).append(p)

    clusters = []
    for cik, plist in by_issuer.items():
        insiders = sorted({p.insider_key for p in plist})
        total = sum(p.value for p in plist)
        if len(insiders) < cfg.min_insiders or total < cfg.min_cluster_value:
            continue
        plist.sort(key=lambda p: (p.tx_date, p.insider))
        clusters.append(Cluster(
            key=f"{cik}:{','.join(insiders)}",
            issuer_cik=cik,
            ticker=plist[0].ticker,
            issuer_name=plist[0].issuer_name,
            purchases=tuple(plist),
            insider_count=len(insiders),
            total_value=total,
            first_date=plist[0].tx_date,
            last_date=plist[-1].tx_date,
        ))
    clusters.sort(key=lambda c: c.total_value, reverse=True)
    return clusters


def find_large_buys(purchases: Iterable[Purchase], cfg: Config, today: date) -> list[Purchase]:
    return [p for p in purchases
            if _eligible(p, cfg, today) and p.value >= cfg.large_buy_usd]
