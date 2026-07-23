# Scott's setup guide

This app runs on the same computer as Trader Workstation (TWS) or IB Gateway. Databento supplies
historical data for backtests. IBKR supplies live prices and executes the MOC/MOO orders. The IBKR
socket is kept on `127.0.0.1` and is never exposed to the public internet.

## 1. Install the two prerequisites

1. Install the latest stable **IBKR Trader Workstation**.
2. Install **uv** from <https://docs.astral.sh/uv/getting-started/installation/>.
3. Download and unzip the latest Half-Day Reversal release.

## 2. Configure TWS paper trading

1. Start TWS and choose **Paper Trading** on the login screen.
2. Sign into paper account `DUH450551`.
3. Open **Global Configuration -> API -> Settings**.
4. Enable **ActiveX and Socket Clients**.
5. Disable **Read-Only API** because paper orders must be transmitted.
6. Set the socket port to `7497`.
7. Enable **Allow connections from localhost only**, or add `127.0.0.1` as a trusted IP.
8. Apply the settings and leave TWS running.

Do not expose port 7497 on the router, firewall or public internet.

## 3. Add the Databento key

### macOS

1. Double-click `start.command`.
2. On the first run it creates and opens `.env`.
3. Remove `#` from the Databento line and paste the key:

   ```text
   DATABENTO_API_KEY=your-key-here
   ```

4. Save `.env`, close TextEdit, and double-click `start.command` again.

### Windows

1. Double-click `start.bat`.
2. On the first run it creates and opens `.env` in Notepad.
3. Add the same `DATABENTO_API_KEY=...` line, save, and run `start.bat` again.

The dashboard opens at <http://127.0.0.1:8765>. The key stays in the local, gitignored `.env` file.

## 4. Connect the paper account safely

1. Open dashboard **Settings**.
2. Select **IBKR paper**.
3. Use host `127.0.0.1`, port `7497`, client ID `17`, account `DUH450551`.
4. For the first test use:
   - capital allocation `0.01`;
   - maximum per position `0.01`;
   - maximum positions `1`;
   - automatic daily run **off**.
5. Save and click **Connect IBKR**.
6. Confirm the dashboard shows the paper account ending `0551`.
7. Click **Preview scan** during regular US market hours.

If the preview reports insufficient market-data coverage, confirm that the live IBKR user has
real-time US equity API data and that it is shared with the paper user. Paper mode can use delayed
quotes for functional testing, but live execution is deliberately blocked without real-time data.

## 5. Verify one complete paper trade

1. Keep TWS and the dashboard open.
2. On a normal NYSE session, return around **3:37-3:44 PM New York time**.
3. Run **Preview scan** and review the selected stock and quantity.
4. Click **Arm session**, type `PAPER`, then click **Scan & execute**.
5. Confirm a paper **MOC BUY** appears in TWS and in the dashboard log.
6. After the close, confirm the filled quantity creates a **MKT / OPG SELL** for the next session.
7. After the next open, confirm the position is flat and the exit is filled.

The time window automatically follows NYSE holidays and early closes. The app will not send an
order outside its pre-close window, twice on the same day, while disarmed, or while an earlier exit
is still open.

## 6. Run the mid-cap backtest

1. In **Version 2 backtest**, click **Load current S&P 400**.
2. Choose dates and leave:
   - bottom fraction `0.10`;
   - portfolio allocation `1.00`;
   - transaction cost `5` bps each way.
3. Click **Estimate Databento cost**.
4. Review the estimate. Increase the download limit only if the displayed cost is acceptable.
5. Click **Run backtest** and review total return, drawdown, win rate and trades.

This uses current iShares IJH holdings as the current S&P MidCap 400 proxy. It is not a
point-in-time constituent database, so a long historical test can contain survivorship bias.

## 7. Move to live only after paper sign-off

1. Stop the dashboard and log out of TWS paper trading.
2. Sign into the live TWS account.
3. Confirm the live TWS socket port, commonly `7496`.
4. Add this exact line to `.env`:

   ```text
   IBKR_LIVE_UNLOCK=YES_I_UNDERSTAND
   ```

5. Restart the dashboard.
6. In Settings choose **IBKR live**, set the live port, and leave account blank for auto-detection.
7. Keep allocation at `0.01`, maximum position at `0.01`, maximum positions at `1`, and automation
   off for the first live test.
8. Connect and run a preview. Continue only if real-time quote coverage passes.
9. Type `LIVE` to arm. Enable the automatic daily run only after the first live MOC/MOO cycle has
   been manually reviewed.

MOC and MOO are auction market orders and do not guarantee a particular execution price.
