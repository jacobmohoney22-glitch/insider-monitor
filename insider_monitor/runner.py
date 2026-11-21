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
               "cluster_alerts": 0, "large_alerts": 0, "fetch_errors": 0, "feed_error": None}

    # 1. collect filings we haven't processed (feed is newest-first)
    fresh, queued, pages_ok = [], set(), 0
    for page in range(cfg.max_pages):
        try:
            entries = client.feed_page(start=page * PAGE_SIZE, count=PAGE_SIZE)
        except requests.RequestException as e:
            summary["feed_error"] = type(e).__name__      # SEC slow/unreachable: not our bug
            break
        pages_ok += 1
        new = [e for e in entries if e.accession not in state.seen and e.accession not in queued]
        if not new:
            break          # reached filings we've already handled
        for e in new:
            queued.add(e.accession)
        fresh.extend(new)

    if pages_ok == 0:
        # Nothing was reachable this run. Skip it quietly (no red X); the next run re-reads the
        # same newest-300 window, so nothing is lost. Warn ONCE if it keeps happening.
        state.feed_failures += 1
        if state.feed_failures >= cfg.feed_alert_after and not state.feed_alerted:
            if notifier.send(f"\u26a0\ufe0f INSIDER MONITOR \u00b7 The SEC filing feed has been unreachable "
                             f"for {state.feed_failures} runs in a row. Alerts are delayed, not lost: "
                             f"it catches up automatically when the SEC responds."):
                state.feed_alerted = True
        summary["feed_failures"] = state.feed_failures
        if persist:
            state.save(cfg.state_path)
        return summary

    if state.feed_failures:                                # the feed is back
        if state.feed_alerted:
            notifier.send(f"\u2705 INSIDER MONITOR \u00b7 The SEC feed is back after "
                          f"{state.feed_failures} missed runs. Catching up now.")
        state.feed_failures, state.feed_alerted = 0, False
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
