# Scott's setup guide

Dashboard: <https://half-day-reversal-production.up.railway.app>

The dashboard is hosted publicly on Railway and protected by a private access key. IBKR live
prices and orders still pass through TWS on Scott's computer. The included connector opens an
outbound encrypted link; port `7497` remains local and must never be exposed publicly.

After this one-time setup, normal actions happen only in the hosted dashboard or TWS.

## 1. Install once

1. Install the latest stable **IBKR Trader Workstation**.
2. Install **uv** from <https://docs.astral.sh/uv/getting-started/installation/>.
3. Download and unzip the latest public release:
   <https://github.com/rivnefurniture-lab/ibkr-half-day-reversal/releases/latest>.
4. Ask Andrii for the private dashboard access key. Do not post it publicly.

## 2. Configure TWS paper trading

1. Start TWS, choose **Paper Trading**, and sign into `DUH450551`.
2. Open **Global Configuration -> API -> Settings**.
3. Enable **ActiveX and Socket Clients**.
4. Disable **Read-Only API** so paper orders can be transmitted.
5. Set the socket port to `7497`.
6. Allow localhost only, or add `127.0.0.1` as a trusted IP.
7. Apply the settings and leave TWS running.

Do not create firewall or router forwarding for port `7497`.

## 3. Configure the connector once

### macOS

1. Double-click `connect-hosted.command`.
2. On first run it creates `.env` and opens it in TextEdit.
3. Set:

   ```text
   HOSTED_DASHBOARD_URL=https://half-day-reversal-production.up.railway.app
   BRIDGE_TOKEN=the-private-access-key-from-Andrii
   DATABENTO_API_KEY=Scott's-Databento-key
   ```

4. Save, close TextEdit, and double-click `connect-hosted.command` again.

### Windows

1. Double-click `connect-hosted.bat`.
2. On first run it creates `.env` and opens it in Notepad.
3. Add the same three values shown above, save, and run `connect-hosted.bat` again.

The connector window stays open and the hosted dashboard opens automatically. Enter the same
private access key when the dashboard asks for it. The browser remembers it on that computer.

The Databento key and IBKR configuration stay in the local, gitignored `.env` and `data` files.
They are not uploaded to the public repository or stored on Railway.

## 4. Connect the paper account

1. In the hosted dashboard, open **Settings**.
2. Select **IBKR paper**.
3. Use host `127.0.0.1`, port `7497`, client ID `17`, account `DUH450551`.
4. For the first test use capital allocation `0.01`, maximum per position `0.01`, maximum
   positions `1`, and automatic daily run **off**.
5. Save and click **Connect IBKR**.
6. Confirm the account label ends in `0551`.
7. Click **Preview scan** during regular US market hours.

If coverage is insufficient, confirm the IBKR user has US-equity market data enabled for API use
and shared with the paper account.

## 5. Verify one complete paper trade

1. Keep TWS and the connector window open.
2. On a normal NYSE session, return around **3:37-3:44 PM New York time**.
3. Run **Preview scan** and review the selected stock and quantity.
4. Click **Arm session**, type `PAPER`, then click **Scan & execute**.
5. Confirm a paper **MOC BUY** appears in TWS and the dashboard journal.
6. After the close, confirm the fill creates a **MKT / OPG SELL** for the next session.
7. After the next open, confirm the exit fills and the position is flat.

The app blocks orders outside its pre-close window, duplicate daily runs, disarmed execution, and
new entries while an earlier exit is open.

## 6. Run the mid-cap backtest

1. In **Version 2 backtest**, click **Load current S&P 400**.
2. Choose dates and leave bottom fraction `0.10`, portfolio allocation `1.00`, and transaction
   cost `5` bps each way.
3. Click **Estimate Databento cost**.
4. Review the estimate and increase the download limit only if acceptable.
5. Click **Run backtest** and review return, drawdown, win rate, and trades.

This uses current iShares IJH holdings as an S&P MidCap 400 proxy. It is not a point-in-time
constituent database, so long historical tests can contain survivorship bias.

## 7. Move to live only after paper sign-off

1. Stop the connector and log out of TWS paper trading.
2. Sign into the live TWS account and confirm the live socket port, commonly `7496`.
3. Add `IBKR_LIVE_UNLOCK=YES_I_UNDERSTAND` to `.env`.
4. Run the hosted connector again.
5. In dashboard Settings choose **IBKR live**, use the live port, and leave account blank for
   auto-detection.
6. Keep allocation at `0.01`, maximum position at `0.01`, maximum positions at `1`, and automation
   off for the first live test.
7. Connect and preview. Continue only if real-time quote coverage passes.
8. Type `LIVE` to arm. Enable automatic daily runs only after manually reviewing the first full
   live MOC/MOO cycle.

MOC and MOO are auction market orders and do not guarantee a particular execution price.
