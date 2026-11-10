from __future__ import annotations

import argparse
import json

from .config import Config
from .edgar import EdgarClient
from .notify import ConsoleNotifier, TelegramNotifier
from .runner import run_once


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="SEC Form 4 insider cluster-buy monitor")
    ap.add_argument("--dry-run", action="store_true",
                    help="print alerts to the console; send nothing and save no state")
    args = ap.parse_args(argv)

    try:                       # optional: load a local .env when running on your machine
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    cfg = Config.from_env()
    cfg.require_sec_identity()
    if args.dry_run:
        notifier = ConsoleNotifier()
    else:
        cfg.require_telegram()
        notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id)

    summary = run_once(cfg, EdgarClient(cfg.user_agent), notifier, persist=not args.dry_run)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
