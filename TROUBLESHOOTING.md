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
