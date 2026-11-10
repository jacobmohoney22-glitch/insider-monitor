from __future__ import annotations

from datetime import datetime, timezone

import requests

from .clusters import find_clusters, find_large_buys
from .config import Config
from .form4 import parse_form4
from .notify import format_cluster, format_large
from .state import State

PAGE_SIZE = 100


def run_once(cfg: Config, client, notifier, now: datetime | None = None,
             persist: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    state = State.load(cfg.state_path)
    first_run = state.is_new
    summary = {"first_run": first_run, "new_filings": 0, "new_purchases": 0,
               "cluster_alerts": 0, "large_alerts": 0, "fetch_errors": 0}

    # 1. collect filings we haven't processed (feed is newest-first)
    fresh, queued = [], set()
    for page in range(cfg.max_pages):
        entries = client.feed_page(start=page * PAGE_SIZE, count=PAGE_SIZE)
        new = [e for e in entries if e.accession not in state.seen and e.accession not in queued]
        if not new:
            break          # reached filings we've already handled
        for e in new:
            queued.add(e.accession)
        fresh.extend(new)
    fresh = fresh[:cfg.max_filings_per_run]

    # 2. parse each new filing
    for entry in fresh:
        try:
            xml = client.form4_xml(entry.index_url)
        except requests.RequestException:
            summary["fetch_errors"] += 1
            continue            # not marked seen -> retried next run
        if xml is not None:
            try:
                summary["new_purchases"] += state.add_purchases(
                    parse_form4(xml, entry.accession, entry.index_url))
            except Exception as e:      # malformed filing: log, don't loop on it forever
                print(f"could not parse {entry.accession}: {type(e).__name__}: {e}")
        state.mark_seen(entry.accession, now)
        summary["new_filings"] += 1

    # 3. alerts
    purchases = state.all_purchases()
    today = now.date()
    pending = [(f"cluster:{c.key}", format_cluster(c), "cluster_alerts")
               for c in find_clusters(purchases, cfg, today)]
    pending += [(f"single:{p.uid}", format_large(p), "large_alerts")
                for p in find_large_buys(purchases, cfg, today)]

    for key, text, counter in pending:
        if key in state.alerted:
            continue
        if first_run:
            state.mark_alerted(key, now)       # baseline: don't blast old history
        elif notifier.send(text):
            state.mark_alerted(key, now)       # only after a successful send
            summary[counter] += 1

    if first_run:
        state.started = now.isoformat()
        notifier.send(f"Insider monitor started. Baseline loaded from {summary['new_filings']} "
                      f"recent Form 4 filings; alerts begin with the next run.")

    # 4. save
    state.prune(now, cfg.window_days)
    if persist:
        state.save(cfg.state_path)
    return summary
