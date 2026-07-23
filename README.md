# Half-Day Reversal Control

A local browser dashboard that scans a configurable US-stock universe, ranks open-to-current
returns, buys the worst-performing decile with IBKR Market-on-Close orders, and queues
Market-on-Open sells after the closing fills arrive.

The app intentionally starts in **dry-run mode**. Dry run can retrieve IBKR data and calculate
orders, but never transmits them.

## What is included

- A clear live dashboard for connection status, account values, positions, rankings, planned or
  submitted orders, and logs.
- Automatic scheduling relative to the actual NYSE close, including early-close sessions.
- Dry-run, IBKR paper, and explicitly unlocked IBKR live modes.
- Daily arming and duplicate-run protection.
- A minimum data-coverage check, capital and per-position limits, and a maximum position count.
- MOC fill monitoring and automatic next-session MOO exit submission.
- Restart recovery for strategy orders still open in IBKR.
- A strategy-only cancel button that does not touch unrelated IBKR orders.
- Cost-gated Databento historical backtests with 5 bps one-way costs.
- A one-click current S&P MidCap 400 proxy universe from iShares IJH holdings.

## First run on macOS

1. Open Trader Workstation or IB Gateway and sign into the **paper account**.
2. In TWS, open **Global Configuration → API → Settings**:
   - enable socket clients;
   - leave **Read-Only API** disabled;
   - use `127.0.0.1` as a trusted IP;
   - confirm the socket port. TWS paper commonly uses `7497`; IB Gateway paper commonly uses
     `4002`.
3. Double-click `start.command` in Finder. The first start installs the isolated dependencies and
   opens `http://127.0.0.1:8765`.
4. Open Settings in the dashboard, choose **IBKR paper**, and enter the matching port.
5. Connect, run **Preview scan**, review the ranking, then arm the session by typing `PAPER`.

The dashboard must remain running and TWS/IB Gateway must remain connected for automatic runs and
fill monitoring.

For the complete Mac/Windows paper-to-live handoff, see [SCOTT_SETUP.md](SCOTT_SETUP.md).

## Strategy defaults

- Decision time: 18 minutes before the scheduled NYSE close.
- Selection: bottom 10% by open-to-current return.
- Safe first-run allocation: 1% of net liquidation, one position maximum.
- Price floor: $5.
- Minimum usable-data coverage: 75%.

The research backtest is configured separately and defaults to the full bottom decile at 100%
portfolio allocation. Live risk settings never silently reduce or change the research result.

The included universe is a convenient liquid large-cap starter list, not a claim to reproduce the
paper's historic S&P 500/400/600 sample. Replace it in Settings with the intended research universe.
The symbol list persists in `data/config.json`.

## Market data

The strategy needs real-time US equity data for actual order decisions. IBKR market-data
subscriptions and API acknowledgement must be active for the logged-in user. Dry-run and paper
modes may fall back to delayed IBKR data for testing. Live mode always requests real-time data and
will fail the coverage check instead of trading on delayed or missing quotes. The quote batch size
defaults to 80 to stay below the common 100-line starting allowance.

## Databento backtesting

Add `DATABENTO_API_KEY` to `.env`, restart the dashboard, and use the **Version 2 backtest** panel.
The panel reproduces the implemented workflow: rank open-to-pre-close returns, buy the bottom
decile at the closing price, sell at the next opening price, and subtract 5 bps on each side.

Use **Load current S&P 400** for a current mid-cap universe. Always click **Estimate Databento
cost** first. The server independently rechecks the estimate and blocks a download above the
user-entered dollar limit. Historical results are research only; Databento bars are not used as
the live execution feed.

## Enabling live mode

Paper-test first. Live mode has two independent locks:

1. Copy `.env.example` to `.env` and add:

   ```text
   IBKR_LIVE_UNLOCK=YES_I_UNDERSTAND
   ```

2. Restart the dashboard, select **IBKR live**, connect to a non-paper account, and type `LIVE` to
   arm that trading session.

Removing that environment value locks live mode again. Credentials are never stored by this app;
authentication remains inside TWS/IB Gateway.

## Verification commands

```bash
uv run python -m compileall -q halfreversal
uv run ruff check .
uv run pytest
node --check static/app.js
```

## Important operational note

MOC orders are market orders into the closing auction, and MOO exits are market orders into the
opening auction. Neither guarantees a particular price. This software makes the workflow
automatable; it does not establish that the strategy remains profitable on current data.
