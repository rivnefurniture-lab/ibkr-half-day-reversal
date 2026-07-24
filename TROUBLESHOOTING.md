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
