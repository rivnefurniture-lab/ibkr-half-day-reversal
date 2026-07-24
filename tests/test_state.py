from __future__ import annotations

import os

import pytest

from halfreversal.models import TradingConfig, TradingMode
from halfreversal.state import RuntimeState


def test_failed_config_write_preserves_active_config_and_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state = RuntimeState(tmp_path)
    original = state.config
    updated = original.model_copy(update={"mode": TradingMode.LIVE, "port": 7496})

    def fail_replace(source, destination) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="No space left on device"):
        state.save_config(updated)

    assert state.config == original
    assert TradingConfig.model_validate_json(state.config_path.read_text()) == original
    assert not state.config_path.with_suffix(".json.tmp").exists()
