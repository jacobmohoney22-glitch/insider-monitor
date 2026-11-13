from __future__ import annotations

import html

import requests

from .clusters import Cluster
from .form4 import Purchase

TELEGRAM_LIMIT = 4096


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _line(p: Purchase) -> str:
    price = f"${p.price:,.2f}" if p.price is not None else "n/a"
    link = f' <a href="{html.escape(p.index_url, quote=True)}">filing</a>' if p.index_url else ""
    return (f"• {_esc(p.insider)} ({_esc(p.role)}): {p.shares:,.0f} sh @ {price} "
            f"= {_money(p.value)} on {p.tx_date}{link}")


def format_cluster(c: Cluster) -> str:
    head = f"🚨 <b>INSIDER CLUSTER BUY: {_esc(c.ticker)}</b> ({_esc(c.issuer_name)})"
    sub = (f"{c.insider_count} insiders bought {_money(c.total_value)} "
           f"between {c.first_date} and {c.last_date}")
    return "\n".join([head, sub, ""] + [_line(p) for p in c.purchases])


def format_large(p: Purchase) -> str:
    return (f"🚨 <b>INSIDER LARGE BUY: {_esc(p.ticker)}</b> ({_esc(p.issuer_name)})\n"
            + _line(p))


def split_message(text: str, limit: int = TELEGRAM_LIMIT - 100) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = limit if cut <= 0 else cut
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks


class ConsoleNotifier:
    def send(self, text: str) -> bool:
        print("---- ALERT ----\n" + text + "\n")
        return True


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def send(self, text: str) -> bool:
        ok = True
        for chunk in split_message(text):
            try:
                r = self.session.post(self.url, timeout=20, json={
                    "chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML",
                    "disable_web_page_preview": True})
                if r.status_code != 200:
                    ok = False
                    # status only: never echo the URL (it contains the bot token)
                    print(f"telegram send failed: HTTP {r.status_code} {r.text[:200]}")
            except requests.RequestException as e:
                ok = False
                print(f"telegram send failed: {type(e).__name__}")
        return ok
