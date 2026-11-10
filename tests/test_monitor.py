from datetime import date, datetime, timezone

import pytest

from insider_monitor.clusters import find_clusters, find_large_buys
from insider_monitor.config import Config
from insider_monitor.edgar import FeedEntry, parse_feed, pick_xml_link
from insider_monitor.form4 import parse_form4
from insider_monitor.notify import format_cluster, split_message
from insider_monitor.runner import run_once
from insider_monitor.state import State
from tests.helpers import FakeClient, FakeNotifier, feed_xml, form4_xml

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def cfg(tmp_path, **kw):
    return Config(sec_name="t", sec_email="t@example.com",
                  state_path=str(tmp_path / "state.json"), **kw)


# ---------- parsing ----------
def test_parses_open_market_purchase_only():
    xml = form4_xml(tx=(("P", "A", 1000, 10.0, "2026-11-03"),
                        ("S", "D", 500, 11.0, "2026-11-03"),     # sale
                        ("A", "A", 800, 0.0, "2026-11-03"),      # grant
                        ("M", "A", 300, 2.0, "2026-11-03")),     # option exercise
                    derivative_code="P")                          # derivative table ignored
    ps = parse_form4(xml, "0001-26-000001", "http://x")
    assert len(ps) == 1
    p = ps[0]
    assert (p.ticker, p.shares, p.price, p.value) == ("ACME", 1000, 10.0, 10000.0)
    assert p.role == "Chief Executive Officer" and p.insider_key == "0000222222"


def test_missing_price_and_garbage_do_not_crash():
    ps = parse_form4(form4_xml(tx=(("P", "A", 100, None, "2026-11-03"),)))
    assert ps[0].price is None and ps[0].value == 0.0
    assert parse_form4(b"<ownershipDocument/>") == []          # holdings-only style filing


def test_joint_filing_counts_as_one_insider():
    xml = form4_xml(owners=(("Fund A", "1"), ("Fund A Manager", "2")))
    (p,) = parse_form4(xml)
    assert p.insider_key == "1" and "Fund A Manager" in p.insider


def test_amendment_collapses_onto_same_trade():
    a = parse_form4(form4_xml(), "acc-1")[0]
    b = parse_form4(form4_xml(), "acc-2")[0]          # 4/A re-reporting the same trade
    assert a.uid == b.uid


# ---------- feed / index ----------
def test_feed_filters_prefix_matches_and_dedupes():
    xml = feed_xml([("4 - Acme (0000111111) (Issuer)", "0001111111-26-000001"),
                    ("4 - Jane Doe (0000222222) (Reporting)", "0001111111-26-000001"),
                    ("424B2 - Some Bank (0000333333)", "0001111111-26-000002"),
                    ("4/A - Beta Inc (0000444444) (Issuer)", "0001111111-26-000003")])
    assert [e.accession for e in parse_feed(xml)] == ["0001111111-26-000001",
                                                       "0001111111-26-000003"]


def test_picks_raw_xml_not_xsl_rendering():
    html = ('<a href="/Archives/edgar/data/1/2/xslF345X05/form4.xml">view</a>'
            '<a href="/Archives/edgar/data/1/2/form4.xml">raw</a>')
    assert pick_xml_link(html) == "https://www.sec.gov/Archives/edgar/data/1/2/form4.xml"
    assert pick_xml_link("<a href='x.htm'>no xml</a>") is None


# ---------- clusters ----------
def purchases(*specs):
    out = []
    for i, (cik, owner_cik, date_, shares, price) in enumerate(specs):
        out += parse_form4(form4_xml(issuer_cik=cik, owners=((f"Person {owner_cik}", owner_cik),),
                                     tx=(("P", "A", shares, price, date_),)), f"acc{i}", "u")
    return out


def test_two_insiders_in_window_is_a_cluster(tmp_path):
    ps = purchases(("1", "A", "2026-11-03", 1000, 20.0), ("1", "B", "2026-11-04", 1000, 20.0))
    (c,) = find_clusters(ps, cfg(tmp_path), TODAY)
    assert c.insider_count == 2 and c.total_value == 40000


@pytest.mark.parametrize("specs", [
    [("1", "A", "2026-11-03", 1000, 20.0)],                                   # one insider
    [("1", "A", "2026-11-03", 1000, 20.0), ("1", "A", "2026-11-04", 1000, 20.0)],  # same insider twice
    [("1", "A", "2026-10-01", 1000, 20.0), ("1", "B", "2026-11-04", 1000, 20.0)],  # outside window
    [("1", "A", "2026-11-03", 10, 20.0), ("1", "B", "2026-11-04", 10, 20.0)],      # too small
    [("1", "A", "2026-11-03", 90000, 0.5), ("1", "B", "2026-11-04", 90000, 0.5)],  # penny stock
    [("1", "A", "2026-11-03", 1000, 20.0), ("2", "B", "2026-11-04", 1000, 20.0)],  # different companies
])
def test_non_clusters(tmp_path, specs):
    assert find_clusters(purchases(*specs), cfg(tmp_path), TODAY) == []


def test_new_insider_changes_cluster_key(tmp_path):
    two = purchases(("1", "A", "2026-11-03", 1000, 20.0), ("1", "B", "2026-11-04", 1000, 20.0))
    three = two + purchases(("1", "C", "2026-11-04", 1000, 20.0))
    assert find_clusters(two, cfg(tmp_path), TODAY)[0].key != find_clusters(three, cfg(tmp_path), TODAY)[0].key


def test_large_single_buy(tmp_path):
    ps = purchases(("1", "A", "2026-11-03", 20000, 20.0))         # $400k
    assert len(find_large_buys(ps, cfg(tmp_path), TODAY)) == 1


# ---------- state / end-to-end ----------
def make_world(accs_specs):
    entries, xmls = [], {}
    for i, (acc, kw) in enumerate(accs_specs):
        entries.append(FeedEntry(acc, "4 - X", f"https://www.sec.gov/Archives/{acc}-index.htm", ""))
        xmls[acc] = form4_xml(**kw)
    return FakeClient(entries, xmls)


def test_end_to_end_alerts_once_and_survives_restart(tmp_path):
    c = cfg(tmp_path)
    n = FakeNotifier()
    base = make_world([("0001-26-000001", dict(issuer_cik="9", owners=(("Old Guy", "5"),),
                                               tx=(("P", "A", 10, 10.0, "2026-11-04"),)))])
    # run 1: baseline -> start message only
    s1 = run_once(c, base, n, now=NOW)
    assert s1["first_run"] and len(n.sent) == 1 and "started" in n.sent[0]

    # run 2: two different insiders buy ACME -> exactly one cluster alert
    world = make_world([
        ("0001-26-000002", dict(owners=(("Jane Doe", "10"),), tx=(("P", "A", 5000, 20.0, "2026-11-04"),))),
        ("0001-26-000003", dict(owners=(("John Roe", "11"),), title="Chief Financial Officer",
                               tx=(("P", "A", 3000, 20.0, "2026-11-05"),))),
        ("0001-26-000001", dict(issuer_cik="9", owners=(("Old Guy", "5"),),
                               tx=(("P", "A", 10, 10.0, "2026-11-04"),)))])
    s2 = run_once(c, world, n, now=NOW)
    assert s2["new_filings"] == 2 and s2["cluster_alerts"] == 1
    assert "ACME" in n.sent[-1] and "Jane Doe" in n.sent[-1] and "$160,000" in n.sent[-1]

    # run 3 (fresh process, same files): nothing new -> no duplicate alert, no refetch
    before = len(n.sent)
    world.fetched.clear()
    s3 = run_once(c, world, n, now=NOW)
    assert s3["new_filings"] == 0 and len(n.sent) == before and world.fetched == []


def test_failed_send_is_retried_next_run(tmp_path):
    c = cfg(tmp_path)
    run_once(c, make_world([]), FakeNotifier(), now=NOW)             # baseline
    world = make_world([
        ("0001-26-000002", dict(owners=(("Jane Doe", "10"),), tx=(("P", "A", 5000, 20.0, "2026-11-04"),))),
        ("0001-26-000003", dict(owners=(("John Roe", "11"),), tx=(("P", "A", 3000, 20.0, "2026-11-05"),)))])
    bad = FakeNotifier(ok=False)
    assert run_once(c, world, bad, now=NOW)["cluster_alerts"] == 0
    good = FakeNotifier()
    assert run_once(c, world, good, now=NOW)["cluster_alerts"] == 1   # sent on retry


def test_corrupt_state_is_not_silently_reset(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    with pytest.raises(SystemExit):
        State.load(str(p))


def test_prune_drops_old_entries():
    s = State()
    s.mark_seen("old", datetime(2026, 9, 1, tzinfo=timezone.utc))
    s.mark_seen("new", NOW)
    s.prune(NOW, 7)
    assert list(s.seen) == ["new"]


def test_split_message_respects_telegram_limit():
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(200))
    assert all(len(c) <= 4096 for c in split_message(text))
