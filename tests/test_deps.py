from __future__ import annotations

import subprocess

import pytest

from rb_wordstat.core import deps
from rb_wordstat.core.errors import DependencyTooOld


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch):
    """Pretend a CLI `other` is on PATH and prints `state["version"]` for --version."""
    state: dict = {"path": "/usr/bin/other", "version": "0.3.1", "returncode": 0}
    monkeypatch.setattr(deps.shutil, "which", lambda name: state["path"] if name == "other" else None)

    def fake_run(argv, **kwargs):
        assert argv == [state["path"], "--version"]
        return subprocess.CompletedProcess(argv, state["returncode"], stdout=f"{state['version']}\n", stderr="")

    monkeypatch.setattr(deps.subprocess, "run", fake_run)
    return state


def test_new_enough_cli_returns_its_path(fake_cli) -> None:
    assert deps.require_cli("other", "0.3.0") == "/usr/bin/other"
    fake_cli["version"] = "0.0.0.post3.dev0+gabc123"  # dev build: accepted
    assert deps.require_cli("other", "0.3.0") == "/usr/bin/other"


def test_old_cli_is_dependency_too_old(fake_cli) -> None:
    fake_cli["version"] = "0.2.9"
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0")
    error = excinfo.value
    assert (error.code, error.exit_code) == ("DEPENDENCY_TOO_OLD", 1)
    assert "0.2.9" in error.message and ">= 0.3.0" in error.message
    assert "uv tool upgrade other" in (error.action or "")


@pytest.mark.parametrize("change", [{"path": None}, {"version": "garbage"}, {"returncode": 1}])
def test_missing_or_unreadable_cli(fake_cli, change: dict) -> None:
    fake_cli.update(change)
    with pytest.raises(DependencyTooOld):
        deps.require_cli("other", "0.3.0")


def test_missing_cli_action_uses_install_url(fake_cli) -> None:
    fake_cli["path"] = None
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0", install_url="https://github.com/example/other")
    pinned = 'uv tool install --reinstall "git+https://github.com/example/other@v0.3.0"'
    assert excinfo.value.action == f"Run '{pinned}', then retry."

    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0")
    action = excinfo.value.action or ""
    assert "<" not in action  # no placeholder to copy-paste
    assert "other >= 0.3.0" in action


def test_old_cli_action_offers_pinned_install_too(fake_cli) -> None:
    fake_cli["version"] = "0.2.0"
    with pytest.raises(DependencyTooOld) as excinfo:
        deps.require_cli("other", "0.3.0", install_url="https://github.com/example/other")
    action = excinfo.value.action or ""
    assert "uv tool upgrade other" in action and "git+https://github.com/example/other@v0.3.0" in action
