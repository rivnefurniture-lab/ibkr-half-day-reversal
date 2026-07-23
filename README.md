# Half-Day Reversal Control

Hosted dashboard: <https://half-day-reversal-production.up.railway.app>

Public releases: <https://github.com/rivnefurniture-lab/ibkr-half-day-reversal/releases/latest>

This dashboard scans a configurable US-stock universe, ranks open-to-current returns, buys the
worst-performing decile with IBKR Market-on-Close orders, and queues Market-on-Open sells after
the closing fills arrive.

Railway hosts the UI. A small connector runs on the same computer as Trader Workstation and opens
an outbound encrypted connection to Railway. TWS remains on `127.0.0.1`; its API port is never
opened to the internet. After the one-time setup, Scott works only in the hosted UI and TWS.

The app starts in **dry-run mode**. Dry run can retrieve IBKR data and calculate orders, but never
transmits them.

## What is included

- Public Railway dashboard with access-key protection.
- Outbound TWS connector with no inbound firewall or router changes.
- Account values, positions, rankings, orders, logs, and downloadable journals.
- Scheduling relative to the actual NYSE close, including early-close sessions.
- Dry-run, IBKR paper, and explicitly unlocked IBKR live modes.
- Daily arming, duplicate-run protection, data-coverage checks, and position limits.
- MOC fill monitoring and automatic next-session MOO exit submission.
- Restart recovery for strategy orders still open in IBKR.
- Strategy-only cancellation that does not touch unrelated IBKR orders.
- Cost-gated Databento historical backtests with 5 bps one-way costs.
- Current S&P MidCap 400 proxy universe from iShares IJH holdings.

## Quick start

1. Download the correct one-click installer from the latest public release:
   - `Half-Day-Reversal-Setup-Windows.exe` for Windows;
   - the `arm64.dmg` for Apple Silicon Macs;
   - the `x86_64.dmg` for Intel Macs.
2. Install and open **Half-Day Reversal Connector**.
3. Enter the dashboard access key and Databento key in the one-time setup window. Leave live mode
   locked during paper testing.
4. In TWS Paper Trading, enable socket clients on port `7497`, disable Read-Only API, and allow
   localhost.
5. The dashboard opens already authenticated. Select **IBKR paper**, connect account `DUH450551`,
   and run a preview.

No Python, `uv`, terminal, `.env`, or script editing is required. The connector can start
automatically with the computer. Keep TWS open while scanning, monitoring fills, or running
automatically.
See [SCOTT_SETUP.md](SCOTT_SETUP.md) for the complete paper-to-live handoff.

## Strategy defaults

- Decision time: 18 minutes before the scheduled NYSE close.
- Selection: bottom 10% by open-to-current return.
- Safe first-run allocation: 1% of net liquidation, one position maximum.
- Price floor: $5.
- Minimum usable-data coverage: 75%.

The research backtest is configured separately and defaults to the full bottom decile at 100%
portfolio allocation. Live risk settings never silently change the research result.

The included universe is a liquid large-cap starter list. Replace it in Settings with the intended
research universe. The symbol list persists locally in `data/config.json`.

## Market data

IBKR supplies the live US-equity prices used for decisions and performs order execution.
Databento supplies historical data for backtests. Dry-run and paper modes may fall back to delayed
IBKR data for functional testing. Live mode requires real-time data and fails the coverage check
instead of trading on delayed or missing quotes.

## Enabling live mode

Paper-test the complete MOC/MOO cycle first. Live mode has two independent locks:

1. Open **Change keys** in the desktop connector, enable **Unlock IBKR live mode**, save, and
   reopen the connector.
2. Select **IBKR live** in the dashboard, connect to the live TWS session, and type `LIVE` to arm
   that trading session.

Turning the desktop checkbox off locks live mode again. IBKR credentials are never stored by the
app; authentication remains in TWS.

## Verification

```bash
uv run python -m compileall -q halfreversal
uv run ruff check .
uv run pytest
node --check static/app.js
```

MOC and MOO are auction market orders and do not guarantee a particular execution price. This
software automates the workflow; it does not establish that the strategy is profitable.
