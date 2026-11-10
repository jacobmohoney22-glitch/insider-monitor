from __future__ import annotations

import os
from dataclasses import dataclass


def _get(env, key, default):
    value = env.get(key)
    return default if value is None or str(value).strip() == "" else str(value).strip()


@dataclass(frozen=True)
class Config:
    sec_name: str = ""
    sec_email: str = ""
    # cluster rules
    window_days: int = 7             # look-back for "same company, several insiders"
    min_insiders: int = 2            # distinct insiders needed for a cluster
    min_cluster_value: float = 25_000.0   # combined $ across the cluster
    min_price: float = 1.0           # ignore sub-$1 stocks (noisy)
    large_buy_usd: float = 250_000.0 # alert on a single purchase this big
    # scan limits
    max_pages: int = 3               # feed pages (100 filings each) per run
    max_filings_per_run: int = 200
    # delivery / storage
    telegram_token: str = ""
    telegram_chat_id: str = ""
    state_path: str = "state/state.json"

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        g = lambda k, d: _get(env, k, d)
        return cls(
            sec_name=g("SEC_NAME", ""),
            sec_email=g("SEC_EMAIL", ""),
            window_days=int(g("WINDOW_DAYS", 7)),
            min_insiders=int(g("MIN_INSIDERS", 2)),
            min_cluster_value=float(g("MIN_CLUSTER_VALUE", 25_000)),
            min_price=float(g("MIN_PRICE", 1.0)),
            large_buy_usd=float(g("LARGE_BUY_USD", 250_000)),
            max_pages=int(g("MAX_PAGES", 3)),
            max_filings_per_run=int(g("MAX_FILINGS_PER_RUN", 200)),
            telegram_token=g("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=g("TELEGRAM_CHAT_ID", ""),
            state_path=g("STATE_PATH", "state/state.json"),
        )

    @property
    def user_agent(self) -> str:
        return f"{self.sec_name} ({self.sec_email})"

    def require_sec_identity(self) -> None:
        if not (self.sec_name and self.sec_email):
            raise SystemExit("SEC_NAME and SEC_EMAIL are required (SEC fair-access policy).")

    def require_telegram(self) -> None:
        if not (self.telegram_token and self.telegram_chat_id):
            raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required "
                             "(or use --dry-run).")
