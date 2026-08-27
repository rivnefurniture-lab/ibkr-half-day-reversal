const $ = (selector) => document.querySelector(selector);
const state = { snapshot: null, busy: false, backtestBusy: false, hosted: false, connectorOnline: true, toastTimer: null };

const elements = {
  modeBadge: $("#modeBadge"), connectionBadge: $("#connectionBadge"), primaryStatus: $("#primaryStatus"),
  statusDetail: $("#statusDetail"), connectButton: $("#connectButton"), scanButton: $("#scanButton"),
  testOrderButton: $("#testOrderButton"), armButton: $("#armButton"),
  executeButton: $("#executeButton"), cancelButton: $("#cancelButton"),
  armDot: $("#armDot"), armLabel: $("#armLabel"), nextRun: $("#nextRun"), marketStatus: $("#marketStatus"),
  netLiq: $("#netLiq"), availableFunds: $("#availableFunds"), accountLabel: $("#accountLabel"),
  universeCount: $("#universeCount"), coverageLabel: $("#coverageLabel"), selectedCount: $("#selectedCount"),
  lastScan: $("#lastScan"), rankingBody: $("#rankingBody"), rankingEmpty: $("#rankingEmpty"),
  rankingTableWrap: $("#rankingTableWrap"), ordersBody: $("#ordersBody"), ordersEmpty: $("#ordersEmpty"),
  ordersTableWrap: $("#ordersTableWrap"), positionsBody: $("#positionsBody"), positionsEmpty: $("#positionsEmpty"),
  positionsTableWrap: $("#positionsTableWrap"), logs: $("#logs"), settingsDialog: $("#settingsDialog"),
  settingsForm: $("#settingsForm"), armDialog: $("#armDialog"), armForm: $("#armForm"), toast: $("#toast"),
  backtestForm: $("#backtestForm"), estimateBacktest: $("#estimateBacktest"),
  loadMidcaps: $("#loadMidcaps"),
  runBacktest: $("#runBacktest"), backtestStatus: $("#backtestStatus"),
  backtestResults: $("#backtestResults"), backtestTradesBody: $("#backtestTradesBody"),
  hostedBadge: $("#hostedBadge"), accessDialog: $("#accessDialog"), accessForm: $("#accessForm"),
  downloadLogs: $("#downloadLogs"), macHelpDialog: $("#macHelpDialog"),
};

async function api(path, options = {}) {
  const accessKey = state.hosted ? localStorage.getItem("halfdayAccessKey") : "";
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(accessKey ? { Authorization: `Bearer ${accessKey}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401 && state.hosted) showAccessDialog(payload.detail);
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg || String(item)).join("; ")
      : payload.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return payload;
}

function loadIndexUniverse(index) {
  const path = state.hosted
    ? `/host/universe?index=${encodeURIComponent(index)}`
    : `/api/backtest/universe/midcap?index=${encodeURIComponent(index)}`;
  return api(path);
}

function showAccessDialog(message = "") {
  $("#accessError").textContent = message;
  $("#accessError").classList.toggle("hidden", !message);
  $("#accessKey").value = localStorage.getItem("halfdayAccessKey") || "";
  if (!elements.accessDialog.open) elements.accessDialog.showModal();
}

function consumePairedAccessKey() {
  const parameters = new URLSearchParams(window.location.hash.slice(1));
  const key = parameters.get("access") || "";
  if (key.length >= 32) {
    localStorage.setItem("halfdayAccessKey", key);
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }
}

function formatMoney(value) {
  if (!value) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatTime(value, includeDate = false) {
  if (!value) return "—";
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", { month: includeDate ? "short" : undefined, day: includeDate ? "numeric" : undefined, hour: "numeric", minute: "2-digit", second: includeDate ? undefined : "2-digit", timeZoneName: "short" }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function render(snapshot) {
  state.snapshot = snapshot;
  state.connectorOnline = true;
  const modeLabels = { dry_run: "Dry run", paper: "IBKR paper", live: "IBKR live" };
  elements.modeBadge.textContent = modeLabels[snapshot.mode];
  elements.modeBadge.className = `badge neutral ${snapshot.mode === "live" ? "live" : ""}`;
  elements.connectionBadge.className = `badge ${snapshot.connected ? "connected" : ""}`;
  elements.connectionBadge.innerHTML = `<i></i>${escapeHtml(snapshot.connection_label)}`;
  elements.connectButton.textContent = snapshot.connected ? "Disconnect" : "Connect IBKR";
  elements.testOrderButton.disabled = !snapshot.connected || snapshot.mode !== "paper" || state.busy;
  elements.scanButton.disabled = !snapshot.connected || state.busy;
  elements.armButton.disabled = !snapshot.connected || state.busy;
  elements.executeButton.disabled = !snapshot.connected || !snapshot.armed || state.busy;
  elements.cancelButton.disabled = !snapshot.connected || state.busy;
  $("#settingsButton").disabled = false;
  elements.loadMidcaps.disabled = state.backtestBusy;
  elements.estimateBacktest.disabled = state.backtestBusy;
  elements.runBacktest.disabled = state.backtestBusy || !elements.runBacktest.dataset.estimated;
  elements.downloadLogs.disabled = false;

  if (!snapshot.connected) {
    elements.primaryStatus.textContent = "Safe and standing by";
    elements.statusDetail.textContent = "Connect IBKR to preview today’s ranking. No orders can be sent yet.";
  } else if (snapshot.armed) {
    elements.primaryStatus.textContent = snapshot.mode === "live" ? "Live execution is armed" : "Ready for today’s run";
    elements.statusDetail.textContent = `Orders are allowed until ${formatTime(snapshot.armed_until)}. Review the ranking before executing manually.`;
  } else {
    elements.primaryStatus.textContent = "Connected in observation mode";
    elements.statusDetail.textContent = "Scanning is available, but execution remains locked until you arm this session.";
  }
  elements.armDot.className = `status-dot ${snapshot.armed ? "armed" : ""}`;
  elements.armLabel.textContent = snapshot.armed ? `Armed until ${formatTime(snapshot.armed_until)}` : "Execution disarmed";
  elements.nextRun.textContent = snapshot.auto_enabled ? formatTime(snapshot.next_run_at, true) : "Disabled";
  elements.marketStatus.textContent = snapshot.market_status;
  elements.netLiq.textContent = formatMoney(snapshot.account.net_liquidation);
  elements.availableFunds.textContent = formatMoney(snapshot.account.available_funds);
  elements.accountLabel.textContent = snapshot.account.account ? `Account ••••${snapshot.account.account.slice(-4)}` : "No account";
  elements.universeCount.textContent = snapshot.config.universe.length;
  elements.capitalLimit = $("#capitalLimit");
  elements.capitalLimit.textContent = `${Math.round(snapshot.config.capital_fraction * 100)}%`;
  $("#maxPositions").textContent = snapshot.config.max_positions;
  $("#coverageLimit").textContent = `${Math.round(snapshot.config.min_data_coverage * 100)}%`;
  renderRankings(snapshot.rankings, snapshot.last_scan_at, snapshot.config.universe.length);
  renderOrders(snapshot.orders);
  renderPositions(snapshot.account.positions);
  renderLogs(snapshot.logs);
}

function renderConnectorOffline() {
  state.snapshot = null;
  state.connectorOnline = false;
  elements.connectionBadge.className = "badge";
  elements.connectionBadge.innerHTML = "<i></i>Connector offline";
  elements.primaryStatus.textContent = "Start the desktop connector";
  elements.statusDetail.textContent = "Open the Half-Day Reversal Connector on the same computer as TWS. This page will reconnect automatically.";
  elements.connectButton.disabled = true;
  elements.testOrderButton.disabled = true;
  elements.scanButton.disabled = true;
  elements.armButton.disabled = true;
  elements.executeButton.disabled = true;
  elements.cancelButton.disabled = true;
  $("#settingsButton").disabled = true;
  elements.loadMidcaps.disabled = true;
  elements.estimateBacktest.disabled = true;
  elements.runBacktest.disabled = true;
  elements.downloadLogs.disabled = true;
  elements.armDot.className = "status-dot";
  elements.armLabel.textContent = "Waiting for desktop connector";
  elements.nextRun.textContent = "—";
  elements.marketStatus.textContent = "Unavailable";
}

function renderRankings(rows, lastScanAt, universeSize) {
  elements.lastScan.textContent = lastScanAt ? `Scanned ${formatTime(lastScanAt)}` : "Not scanned yet";
  elements.selectedCount.textContent = rows.filter((row) => row.selected).length || "—";
  elements.coverageLabel.textContent = rows.length ? `${rows.length}/${universeSize} usable quotes` : "Waiting for scan";
  elements.rankingEmpty.classList.toggle("hidden", rows.length > 0);
  elements.rankingTableWrap.classList.toggle("hidden", rows.length === 0);
  elements.rankingBody.innerHTML = rows.slice(0, 60).map((row) => `
    <tr class="${row.selected ? "selected" : ""}">
      <td>${row.rank}</td><td class="symbol">${escapeHtml(row.symbol)}</td>
      <td>$${row.open_price.toFixed(2)}</td><td>$${row.current_price.toFixed(2)}</td>
      <td class="${row.return_pct < 0 ? "negative" : "positive"}">${row.return_pct > 0 ? "+" : ""}${row.return_pct.toFixed(2)}%</td>
      <td>${row.selected ? `${row.target_quantity.toLocaleString()} · ${formatMoney(row.target_value)}` : "—"}</td>
    </tr>`).join("");
}

function renderOrders(orders) {
  elements.ordersEmpty.classList.toggle("hidden", orders.length > 0);
  elements.ordersTableWrap.classList.toggle("hidden", orders.length === 0);
  elements.ordersBody.innerHTML = orders.map((order) => `<tr>
    <td>${formatTime(order.created_at)}</td><td class="symbol">${escapeHtml(order.symbol)}</td><td>${order.side}</td>
    <td>${order.order_type}</td><td>${order.quantity.toLocaleString()}</td><td><span class="order-status">${escapeHtml(order.status)}</span></td>
  </tr>`).join("");
}

function renderPositions(positions) {
  elements.positionsEmpty.classList.toggle("hidden", positions.length > 0);
  elements.positionsTableWrap.classList.toggle("hidden", positions.length === 0);
  elements.positionsBody.innerHTML = positions.map((position) => `<tr><td class="symbol">${escapeHtml(position.symbol)}</td><td>${position.quantity.toLocaleString()}</td><td>$${position.average_cost.toFixed(2)}</td></tr>`).join("");
}

function renderLogs(logs) {
  elements.logs.innerHTML = logs.length ? logs.map((entry) => `<div class="log-row"><time>${formatTime(entry.timestamp)}</time><span class="log-level ${entry.level.toLowerCase()}">${entry.level}</span><p>${escapeHtml(entry.message)}</p></div>`).join("") : `<div class="compact-empty">No log entries yet.</div>`;
}

function backtestRequest() {
  const symbols = $("#backtestUniverse").value.split(/[\s,;]+/).filter(Boolean);
  const capitalFraction = Number($("#backtestCapitalFraction").value);
  if (!Number.isFinite(capitalFraction) || capitalFraction < 0.01 || capitalFraction > 1) {
    throw new Error("Portfolio allocation must be between 0.01 and 1.00. Use 1.00 for 100% or 0.10 for 10%.");
  }
  return {
    start_date: $("#backtestStart").value,
    end_date: $("#backtestEnd").value,
    max_cost_usd: Number($("#backtestMaxCost").value),
    transaction_cost_bps: Number($("#backtestCostBps").value),
    bottom_fraction: Number($("#backtestBottomFraction").value),
    capital_fraction: capitalFraction,
    universe: symbols.length ? symbols : null,
  };
}

function setBacktestBusy(busy) {
  state.backtestBusy = busy;
  elements.loadMidcaps.disabled = busy;
  elements.estimateBacktest.disabled = busy;
  elements.runBacktest.disabled = busy || !elements.runBacktest.dataset.estimated;
}

function renderBacktest(result) {
  const percentage = (value) => `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  $("#btTotalReturn").textContent = percentage(result.total_return_pct);
  $("#btTotalReturn").className = result.total_return_pct < 0 ? "negative" : "positive";
  $("#btAnnualized").textContent = percentage(result.annualized_return_pct);
  $("#btDrawdown").textContent = percentage(result.max_drawdown_pct);
  $("#btWinRate").textContent = `${result.win_rate_pct.toFixed(1)}%`;
  $("#btTrades").textContent = result.trade_count.toLocaleString();
  $("#btEquity").textContent = formatMoney(result.ending_equity);
  elements.backtestTradesBody.innerHTML = result.trades.slice().reverse().map((trade) => `<tr>
    <td>${escapeHtml(trade.signal_date)}</td><td class="symbol">${escapeHtml(trade.symbol)}</td>
    <td class="${trade.signal_return_pct < 0 ? "negative" : "positive"}">${percentage(trade.signal_return_pct)}</td>
    <td>$${trade.entry_price.toFixed(2)}</td><td>$${trade.exit_price.toFixed(2)}</td>
    <td class="${trade.return_pct < 0 ? "negative" : "positive"}">${percentage(trade.return_pct)}</td>
  </tr>`).join("");
  elements.backtestResults.classList.remove("hidden");
  elements.backtestStatus.textContent = `${result.sessions_traded}/${result.sessions} sessions traded · ${result.skipped_sessions} skipped · estimated data cost $${result.estimate.estimated_cost_usd.toFixed(4)}`;
}

function populateSettings(config) {
  $("#mode").value = config.mode; $("#host").value = config.host; $("#port").value = config.port;
  $("#clientId").value = config.client_id; $("#account").value = config.account; $("#autoEnabled").checked = config.auto_enabled;
  $("#scanMinutes").value = config.scan_minutes_before_close; $("#bottomFraction").value = config.bottom_fraction;
  $("#capitalFraction").value = config.capital_fraction; $("#maxPositionFraction").value = config.max_position_fraction;
  $("#maxPositionsInput").value = config.max_positions; $("#minPrice").value = config.min_price;
  $("#minCoverage").value = config.min_data_coverage; $("#batchSize").value = config.quote_batch_size;
  $("#universe").value = config.universe.join("\n"); $("#settingsError").classList.add("hidden");
}

function configFromForm() {
  const current = state.snapshot.config;
  return { ...current, mode: $("#mode").value, host: $("#host").value.trim(), port: Number($("#port").value),
    client_id: Number($("#clientId").value), account: $("#account").value.trim(), auto_enabled: $("#autoEnabled").checked,
    scan_minutes_before_close: Number($("#scanMinutes").value), bottom_fraction: Number($("#bottomFraction").value),
    capital_fraction: Number($("#capitalFraction").value), max_position_fraction: Number($("#maxPositionFraction").value),
    max_positions: Number($("#maxPositionsInput").value), min_price: Number($("#minPrice").value),
    min_data_coverage: Number($("#minCoverage").value), quote_batch_size: Number($("#batchSize").value),
    universe: $("#universe").value.split(/[\s,;]+/).filter(Boolean) };
}

async function withBusy(action, successMessage, rethrow = false) {
  if (state.busy) return;
  state.busy = true;
  if (state.snapshot) render(state.snapshot);
  try { const result = await action(); if (successMessage) showToast(successMessage); await refresh(); return result; }
  catch (error) { showToast(error.message, true); if (rethrow) throw error; return null; }
  finally { state.busy = false; if (state.snapshot) render(state.snapshot); }
}

function showToast(message, isError = false) {
  clearTimeout(state.toastTimer); elements.toast.textContent = message; elements.toast.className = `toast ${isError ? "error" : ""}`;
  state.toastTimer = setTimeout(() => elements.toast.classList.add("hidden"), 5000);
}

async function refresh() {
  if (state.hosted && !localStorage.getItem("halfdayAccessKey")) return;
  if (state.hosted) {
    try {
      const hostResponse = await fetch("/host/config");
      if (hostResponse.ok) {
        const host = await hostResponse.json();
        if (!host.worker_connected) {
          renderConnectorOffline();
          return;
        }
      }
    } catch (_) {
      renderConnectorOffline();
      return;
    }
  }
  try { render(await api("/api/status")); } catch (error) { showToast(`Dashboard connection lost: ${error.message}`, true); }
}

async function initialize() {
  consumePairedAccessKey();
  try {
    const response = await fetch("/host/config");
    if (response.ok) {
      state.hosted = true;
      elements.hostedBadge.classList.remove("hidden");
      if (!localStorage.getItem("halfdayAccessKey")) {
        showAccessDialog();
        return;
      }
    }
  } catch (_) {}
  await refresh();
}

elements.connectButton.addEventListener("click", () => {
  if (!state.snapshot) return;
  withBusy(() => api(state.snapshot.connected ? "/api/disconnect" : "/api/connect", { method: "POST" }), state.snapshot.connected ? "Disconnected" : "IBKR connected");
});
elements.testOrderButton.addEventListener("click", async () => {
  if (!confirm("Run a one-share SPY MOC what-if through IBKR Paper? This validates the order path but does not transmit an order.")) return;
  await withBusy(
    () => api("/api/paper-order-test", { method: "POST" }),
    "Paper order path passed — no order was transmitted",
  );
});
elements.scanButton.addEventListener("click", () => withBusy(() => api("/api/scan?execute=false", { method: "POST" }), "Preview scan complete"));
elements.executeButton.addEventListener("click", () => withBusy(() => api("/api/scan?execute=true", { method: "POST" }), "Execution run submitted"));
elements.cancelButton.addEventListener("click", async () => { if (confirm("Cancel all still-open MOC entry orders created by this strategy? Existing MOO exits will remain protected.")) await withBusy(() => api("/api/cancel", { method: "POST" }), "Entry cancellation requested"); });
$("#settingsButton").addEventListener("click", () => {
  if (!state.snapshot) return;
  populateSettings(state.snapshot.config);
  elements.settingsDialog.showModal();
});
$("#closeSettings").addEventListener("click", () => elements.settingsDialog.close());
$("#resetSettings").addEventListener("click", () => elements.settingsDialog.close());
elements.settingsForm.addEventListener("submit", async (event) => { event.preventDefault(); try { await withBusy(() => api("/api/config", { method: "PUT", body: JSON.stringify(configFromForm()) }), "Settings saved", true); elements.settingsDialog.close(); } catch (error) { $("#settingsError").textContent = error.message; $("#settingsError").classList.remove("hidden"); } });
elements.armButton.addEventListener("click", () => { const mode = state.snapshot.mode; const phrase = mode === "live" ? "LIVE" : mode === "paper" ? "PAPER" : "DRY RUN"; $("#armTitle").textContent = `Arm ${mode.replace("_", " ")} execution`; $("#armMessage").textContent = `Type ${phrase} to allow one strategy run for this session.`; $("#armPhrase").value = ""; elements.armDialog.showModal(); $("#armPhrase").focus(); });
$("#cancelArm").addEventListener("click", () => elements.armDialog.close());
elements.armForm.addEventListener("submit", async (event) => { event.preventDefault(); try { await withBusy(() => api("/api/arm", { method: "POST", body: JSON.stringify({ phrase: $("#armPhrase").value }) }), "Execution armed", true); elements.armDialog.close(); } catch (_) {} });

elements.accessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = $("#accessKey").value.trim();
  if (key.length < 32) {
    showAccessDialog("The access key must contain at least 32 characters");
    return;
  }
  localStorage.setItem("halfdayAccessKey", key);
  elements.accessDialog.close();
  await refresh();
});

$("#macHelpButton").addEventListener("click", () => {
  if (!elements.macHelpDialog.open) elements.macHelpDialog.showModal();
});

document.querySelectorAll(".mac-download").forEach((download) => {
  download.addEventListener("click", () => {
    window.setTimeout(() => {
      if (!elements.macHelpDialog.open && !elements.accessDialog.open) {
        elements.macHelpDialog.showModal();
      }
    }, 1200);
  });
});

elements.downloadLogs.addEventListener("click", async () => {
  try {
    const accessKey = state.hosted ? localStorage.getItem("halfdayAccessKey") : "";
    const response = await fetch("/api/logs/download", {
      headers: accessKey ? { Authorization: `Bearer ${accessKey}` } : {},
    });
    if (response.status === 401 && state.hosted) showAccessDialog("Enter the hosted dashboard access key");
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Log download failed (${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const disposition = response.headers.get("content-disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "half-day-reversal.log";
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showToast(error.message, true);
  }
});

elements.estimateBacktest.addEventListener("click", async () => {
  setBacktestBusy(true);
  elements.backtestStatus.textContent = "Checking Databento price…";
  try {
    const request = backtestRequest();
    const estimate = await api("/api/backtest/estimate", { method: "POST", body: JSON.stringify(request) });
    const allowed = estimate.estimated_cost_usd <= request.max_cost_usd;
    elements.backtestStatus.textContent = `Estimated download: $${estimate.estimated_cost_usd.toFixed(4)} for ${estimate.symbol_count} symbols`;
    elements.runBacktest.dataset.estimated = allowed ? "true" : "";
    if (!allowed) showToast(`Estimate exceeds your $${request.max_cost_usd.toFixed(2)} download limit`, true);
  } catch (error) {
    elements.runBacktest.dataset.estimated = "";
    elements.backtestStatus.textContent = error.message;
    showToast(error.message, true);
  } finally {
    setBacktestBusy(false);
  }
});

elements.loadMidcaps.addEventListener("click", async () => {
  setBacktestBusy(true);
  elements.backtestStatus.textContent = "Loading current index holdings…";
  try {
    const index = $("#universeIndex").value;
    const universe = await loadIndexUniverse(index);
    $("#backtestUniverse").value = universe.symbols.join("\n");
    elements.runBacktest.dataset.estimated = "";
    elements.backtestStatus.textContent = `Loaded ${universe.symbol_count} symbols from ${universe.source}${universe.as_of ? ` · ${universe.as_of}` : ""}`;
    showToast("Universe loaded");
  } catch (error) {
    elements.backtestStatus.textContent = "Could not load the index universe";
    showToast(error.message, true);
  } finally {
    setBacktestBusy(false);
  }
});

$("#loadSettingsMidcaps").addEventListener("click", async () => {
  const button = $("#loadSettingsMidcaps");
  button.disabled = true;
  try {
    const universe = await loadIndexUniverse("smallcap600");
    $("#universe").value = universe.symbols.join("\n");
    showToast(`Loaded ${universe.symbol_count} current S&P 600 symbols. Save settings to use them for live scans.`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
});

elements.backtestForm.addEventListener("input", () => {
  elements.runBacktest.dataset.estimated = "";
  elements.runBacktest.disabled = true;
  elements.backtestStatus.textContent = "Estimate cost again after changing inputs";
});

elements.backtestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBacktestBusy(true);
  elements.backtestStatus.textContent = "Downloading and calculating…";
  try {
    const result = await api("/api/backtest/run", { method: "POST", body: JSON.stringify(backtestRequest()) });
    renderBacktest(result);
    showToast("Backtest complete");
  } catch (error) {
    elements.backtestStatus.textContent = "Backtest failed";
    showToast(error.message, true);
  } finally {
    setBacktestBusy(false);
  }
});

const today = new Date();
const start = new Date(today);
start.setDate(today.getDate() - 30);
$("#backtestEnd").value = today.toISOString().slice(0, 10);
$("#backtestStart").value = start.toISOString().slice(0, 10);

initialize();
setInterval(refresh, 3000);
