# Scott's one-click setup

Dashboard: <https://half-day-reversal-production.up.railway.app>

The dashboard is hosted on Railway. The desktop connector keeps the IBKR API on Scott's computer
and opens only an outbound encrypted link. Port `7497` is never exposed publicly.

## 1. Install the connector

Download the latest release:
<https://github.com/rivnefurniture-lab/ibkr-half-day-reversal/releases/latest>

- **Already installed:** replace the old app with version `1.2.4`, then open it normally. The new
  connector keeps the saved keys and automatically repairs an older connector left running in the
  background.
- **Windows:** run `Half-Day-Reversal-Setup-Windows.exe`.
- **Apple Silicon Mac:** open `Half-Day-Reversal-macOS-arm64.dmg`, then drag the app to
  Applications.
- **Intel Mac:** open `Half-Day-Reversal-macOS-x86_64.dmg`, then drag the app to Applications.

On a Mac, Apple may block the first launch because this build is not notarized:

1. Try to open the connector once, then close Apple's warning.
2. Open **System Settings -> Privacy & Security**.
3. Scroll to **Security**, click **Open Anyway**, and confirm.

The dashboard's **Mac blocked the app?** button opens this screen directly. This exception is
needed only once. Apple's instructions:
<https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac>

## 2. Complete the one-time screen

Open **Half-Day Reversal Connector** and enter:

- the dashboard access key supplied by Andrii;
- Scott's Databento API key.

Leave **Start the connector automatically** checked. Leave **Unlock IBKR live mode** unchecked
until paper testing is signed off. Click **Save and open dashboard**.

The keys are stored privately in Scott's user application-data folder. They are not uploaded to
GitHub or Railway. The dashboard opens already authenticated, so the keys are entered only once.
The running screen must show **Connector version 1.2.4**.

## 3. Configure TWS Paper

1. Open TWS, choose **Paper Trading**, and sign into `DUH450551`.
2. Go to **Global Configuration -> API -> Settings**.
3. Enable **ActiveX and Socket Clients**.
4. Disable **Read-Only API**.
5. Set socket port `7497`.
6. Allow localhost only, or trust `127.0.0.1`.
7. Apply the settings and leave TWS open.

Do not create firewall or router forwarding for port `7497`.

## 4. Connect and preview

1. In the hosted dashboard, open **Settings**.
2. Select **IBKR paper**.
3. Use host `127.0.0.1`, port `7497`, client ID `17`, account `DUH450551`.
4. Set capital allocation `0.01`, maximum per position `0.01`, maximum positions `1`, and keep
   automatic daily runs off.
5. Save, click **Connect IBKR**, and confirm the account label ends in `0551`.
6. Click **Test paper order path**. This asks IBKR to validate a one-share SPY MOC what-if but does
   not transmit an order. Confirm the green success message. If IBKR rejects the simulation, the
   dashboard shows the actual rejection instead of reporting a false pass.
7. Click **Preview scan** during regular US market hours.

If quote coverage is insufficient, confirm the IBKR user has US-equity market data enabled for
API use and shared with the paper account.

If the connector does not become online within 30 seconds, click **Open diagnostics** in the
connector and send `connector.log` to Andrii. The log never contains either access key.

## 5. Verify one paper MOC/MOO cycle

1. Keep TWS open. The connector can remain minimized.
2. On a normal NYSE session, return around **3:37-3:44 PM New York time**.
3. Run **Preview scan** and review the selected stock and quantity.
4. Click **Arm session**, type `PAPER`, then click **Scan & execute**.
5. Confirm the paper **MOC BUY** in both TWS and the dashboard.
6. After the close, confirm a **MKT / OPG SELL** is queued for the next session.
7. After the next open, confirm the exit fills and the position is flat.

The app blocks execution outside its pre-close window, duplicate daily runs, disarmed execution,
and new entries while an earlier exit remains open.

## 6. Run the mid-cap backtest

1. Click **Load current S&P 400** in the backtest panel.
2. Choose dates and leave bottom fraction `0.10`, portfolio allocation `1.00`, and cost `5` bps
   each way.
3. Click **Estimate Databento cost**.
4. Review the estimate, then click **Run backtest**.

The current iShares IJH holdings are used as the S&P MidCap 400 proxy. This is not a point-in-time
constituent database, so long tests can contain survivorship bias.

## 7. Move to live only after paper sign-off

1. Open the connector and click **Change keys**.
2. Enable **Unlock IBKR live mode**, save, and reopen the connector.
3. Sign into the live TWS account and confirm its socket port, commonly `7496`.
4. In dashboard Settings choose **IBKR live**, use the live port, and leave account blank for
   auto-detection.
5. Keep allocation at `0.01`, maximum position `0.01`, one position, and automation off.
6. Connect and preview. Continue only if real-time coverage passes.
7. Type `LIVE` to arm. Enable automatic runs only after manually reviewing the first live cycle.

MOC and MOO are auction market orders and do not guarantee a particular execution price.
