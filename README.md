# Insider Monitor

Watches SEC EDGAR for **Form 4** insider filings and sends a Telegram alert when
**several different insiders buy the same company's stock on the open market** (a "cluster buy"),
or when one insider makes a very large purchase.

Rebuilt from the idea in `vcsniper7/sec_bot`, with real cluster detection, no repeat alerts,
and tests. Not financial advice; insider buying is a signal, not a guarantee.

## How it works

Every run (about every 10 minutes during filing hours):

1. Read EDGAR's "latest Form 4 filings" feed (up to 3 pages), skipping filings already handled.
2. Download each new filing's raw XML and keep only open-market purchases (code `P`).
3. Look back `WINDOW_DAYS` and flag companies with `MIN_INSIDERS`+ *distinct* insiders and at
   least `MIN_CLUSTER_VALUE` combined. Jointly filed forms count as one insider.
4. Alert once per cluster. If another insider joins later, you get an updated alert.
5. Save state to a `monitor-state` branch (single force-pushed commit) so nothing repeats.

The first run only builds a baseline and sends "monitor started"; alerts begin on run two.

## Setup (about 10 minutes)

1. **Telegram bot:** message `@BotFather` -> `/newbot` -> copy the token. Message your new bot
   `/start`. Get your chat ID from `@userinfobot`.
2. **Create a GitHub repo** and push this folder to it.
3. **Add secrets** (Settings > Secrets and variables > Actions > *Secrets*):
   `SEC_NAME`, `SEC_EMAIL` (SEC requires an identifying User-Agent),
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
4. **Test:** Actions tab > *Insider monitor* > *Run workflow* with **dry run** ticked, and read the log.
5. Run it once without dry run (baseline), then let the schedule take over.

## Tuning (optional repository *variables*)

| Variable | Default | Meaning |
|---|---|---|
| `WINDOW_DAYS` | 7 | Look-back for a cluster |
| `MIN_INSIDERS` | 2 | Distinct insiders required |
| `MIN_CLUSTER_VALUE` | 25000 | Combined purchase value in USD |
| `MIN_PRICE` | 1.0 | Ignore stocks priced below this |
| `LARGE_BUY_USD` | 250000 | Alert on any single purchase this large |

## Schedule and cost

GitHub's minimum schedule interval is 5 minutes and runs can be delayed by minutes under load.
Public repos get unlimited Actions minutes; private repos on the free plan get a monthly
allowance, so use the 15-minute minutes noted in `monitor.yml` for a private repo.
GitHub also disables scheduled workflows after 60 days with no repo activity; re-enable in the
Actions tab (or push any commit).

## Run locally

```
pip install -r requirements-dev.txt
cp .env.example .env      # fill in, never commit
python -m pytest          # tests use synthetic filings, no network
python -m insider_monitor --dry-run
```

## Known limits

* Written and unit-tested against synthetic Form 4 files; **not yet run against live EDGAR**.
  Do a dry run first and check the log.
* Form 4s are filed up to two business days after the trade, so the edge is processing speed.
* Only common-stock open-market purchases are counted (no options, grants or sales).
