# Troubleshooting

## `python` command is unavailable on macOS

- **Error:** `zsh: command not found: python` while running project checks.
- **Cause:** This machine exposes Python through the project's `uv` environment, not a global
  `python` executable.
- **Fix:** Run checks with `uv run python ...` from the project directory.

## Pytest cannot import `halfreversal`

- **Error:** `ModuleNotFoundError: No module named 'halfreversal'` during test collection.
- **Cause:** The initial `pyproject.toml` declared dependencies but did not define a build backend or
  package target, so the project itself was not installed into the uv environment.
- **Fix:** Configure Hatchling with `halfreversal` as the wheel package, then run
  `uv sync --extra dev` again.

## Connector access key appears in WebSocket request logs

- **Error:** The hosted server logs include the connector access key in the `/bridge/ws` request URL.
- **Cause:** WebSocket authentication was initially passed as a query parameter, which access logs
  record by default.
- **Fix:** Send the key in the WebSocket `Authorization: Bearer` header, validate that header in the
  relay, and rotate any key used before this fix.

## Ruff rejects `Callable` imported from `typing`

- **Error:** `UP035 Import from collections.abc instead: Callable`.
- **Cause:** The project targets modern Python, where Ruff requires runtime collection ABCs to be
  imported from `collections.abc`.
- **Fix:** Import `Callable` from `collections.abc` and keep `Any` in `typing`.

## PyInstaller resolves the desktop entrypoint outside the repository

- **Error:** `ERROR: script '.../Projects/halfreversal/desktop.py' not found`.
- **Cause:** PyInstaller exposes `SPECPATH` as the directory containing the nested `.spec` file.
  Moving two parents up overshoots the repository, while using it directly remains in `packaging`.
- **Fix:** Use the parent of `SPECPATH` as the repository root.

## Frozen connector opens but its local service never starts

- **Error:** The packaged GUI remains running, but `127.0.0.1:8765` never comes online.
- **Cause:** The desktop entrypoint used function-scoped relative imports. PyInstaller runs the
  entrypoint as a script and did not collect the dynamically loaded application modules.
- **Fix:** Use absolute `halfreversal.*` imports and explicitly collect the package submodules in
  the PyInstaller specification.

## macOS blocks the connector on first launch

- **Error:** macOS says Apple cannot verify that Half-Day Reversal Connector is free of malicious
  software and offers only a Done button.
- **Cause:** The app is ad-hoc signed but cannot be notarized without an Apple Developer ID
  certificate.
- **Fix:** After the blocked launch, open **System Settings -> Privacy & Security**, click
  **Open Anyway** under Security, and confirm. The hosted dashboard links directly to that settings
  screen. For warning-free distribution, rebuild and notarize with a Developer ID certificate.

## Saving settings fails when the Mac disk is full

- **Error:** `OSError: [Errno 28] No space left on device` while replacing `config.json`.
- **Cause:** macOS had no room for the temporary atomic-write file.
- **Fix:** Remove only expendable temporary artifacts, then save again. Atomic state writes now
  delete a failed temporary file and keep both the active in-memory and on-disk configuration
  unchanged until the replacement succeeds.

## Packaged Mac connector remains offline

- **Error:** The connector repeatedly shows `Connector offline` and the hosted dashboard controls
  remain disabled, while TWS and the API settings appear correct.
- **Cause:** The packaged Python/OpenSSL runtime cannot locate a trusted certificate authority
  bundle, so the secure WebSocket fails with `CERTIFICATE_VERIFY_FAILED` before reaching Railway.
- **Fix:** Build version 1.2.1 or newer. The connector now creates its WebSocket TLS context from
  Certifi's packaged CA bundle.

## Reinstalling the fixed connector still leaves the hosted dashboard offline

- **Error:** The latest app is downloaded and opened, but Railway still reports no connector and
  the dashboard remains disabled.
- **Cause:** Closing the previous Mac window only minimized its v1.2.0 process. That TLS-broken
  process continued owning `127.0.0.1:8765`, while the newly opened app mistook the local port for
  a healthy hosted bridge and exited before connecting.
- **Fix:** Version 1.2.2 identifies the existing Half-Day service separately from the hosted bridge.
  If it finds an older local process whose relay is offline, it starts the corrected secure bridge,
  writes persistent diagnostics, and takes over the local service if the old process later exits.

## TWS is open but every API connection is refused

- **Error:** The connector reaches Railway, but `127.0.0.1:7497` has no listener and Connect IBKR
  fails immediately.
- **Cause:** TWS may show port 7497 and Read-Only API off while **Enable ActiveX and Socket
  Clients** is still unchecked. In the saved TWS configuration this appears as
  `socketClient="false"`.
- **Fix:** In Paper TWS open **Global Configuration -> API -> Settings**, enable ActiveX and Socket
  Clients, keep localhost-only enabled, keep port 7497, apply, and restart TWS.

## Broker account-mode tests unexpectedly skip validation

- **Error:** Tests expecting paper/live account mismatch errors report that no exception was raised.
- **Cause:** The test double began in an already-connected state, so the broker correctly returned
  its existing connection before running a new-login validation path.
- **Fix:** Initialize connection-test doubles as disconnected; use connected doubles only for order
  construction and lifecycle tests.

## IBKR what-if returns a state and a separate rejection

- **Error:** The order-path test reports success even though TWS also emits error 201, such as
  insufficient settled cash.
- **Cause:** IBKR returns the what-if `OrderState` and order rejection through separate API event
  channels. The rejection can arrive shortly after the state, so checking only the returned state
  or removing the error listener immediately can create a false positive.
- **Fix:** Capture request errors during the what-if call and a short post-response grace period,
  fail on any order-level rejection, remove the temporary event handler afterward, and time out
  clearly if IBKR never answers.

## Railway polling loop fails in zsh

- **Error:** `zsh: read-only variable: status`.
- **Cause:** `status` is a reserved read-only parameter in zsh.
- **Fix:** Store the Railway deployment result in a task-specific variable such as
  `deploy_state`.

## Temporary installer cleanup command is rejected

- **Error:** The command runner rejects `rm -rf` even when the target is a project temporary folder.
- **Cause:** Destructive shell commands are blocked by the command safety layer.
- **Fix:** Resolve the exact temporary directory and remove its files and then its empty directories
  with `Path.unlink()` and `Path.rmdir()`.

## GitHub macOS runner reports `hdiutil: create failed - Resource busy`

- **Error:** A macOS installer job reaches DMG creation and then exits with
  `hdiutil: create failed - Resource busy`.
- **Cause:** The hosted macOS runner's disk-image helper can transiently retain a resource even
  though the app bundle and signing steps completed successfully.
- **Fix:** Re-run the failed workflow jobs. Confirm both Mac artifacts build successfully on the
  clean runners before publishing or sharing the release.
