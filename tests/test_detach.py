"""scripts/run_detached.sh / runs_status.sh / detach.py: long commands that outlive the agent's turn."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sessions and process groups")


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    return tmp_path / "runs"


def sh(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPTS / script), *args], capture_output=True, text=True, check=False)  # noqa: S603


def status(label: str) -> dict:
    result = sh("runs_status.sh", label, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["runs"][0]


def wait_for(label: str, state: str, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while (current := status(label))["state"] != state:
        assert time.monotonic() < deadline, current
        time.sleep(0.1)
    return current


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_a_run_records_output_errors_and_exit_code(runs: Path) -> None:
    code = "import sys; print('step 1'); print('boom', file=sys.stderr); sys.exit(3)"
    started = sh("run_detached.sh", "job", *py(code))
    assert started.returncode == 0, started.stderr
    assert "job" in started.stdout

    done = wait_for("job", "done")
    assert done["exit_code"] == 3
    assert done["log_tail"] == ["step 1"]
    assert done["stderr_tail"] == ["boom"]
    assert (runs / "job.pid").is_file()

    human = sh("runs_status.sh")
    assert "job: failed, exit 3" in human.stdout and "boom" in human.stdout


def test_the_run_is_in_its_own_session(runs: Path) -> None:
    sh("run_detached.sh", "session", *py("import os; print(os.getsid(0))"))
    run = wait_for("session", "done")
    assert int(run["log_tail"][0]) != os.getsid(0)  # an interrupt of this session doesn't reach it
    assert int(run["log_tail"][0]) == run["pid"]


def test_stop_ends_the_command_and_records_it(runs: Path) -> None:
    sh("run_detached.sh", "sleeper", "--", *py("import time; time.sleep(60)"))
    assert status("sleeper")["state"] == "running"
    again = sh("run_detached.sh", "sleeper", *py("pass"))
    assert again.returncode == 1 and "still running" in again.stderr

    stopped = subprocess.run([sys.executable, str(SCRIPTS / "detach.py"), "stop", "sleeper"], check=False)  # noqa: S603
    assert stopped.returncode == 0
    assert wait_for("sleeper", "done")["exit_code"] == -15  # SIGTERM


def test_killed_outright(runs: Path) -> None:
    sh("run_detached.sh", "victim", *py("import time; time.sleep(60)"))
    os.killpg(status("victim")["pid"], 9)
    assert "exit_code" not in wait_for("victim", "killed")  # SIGKILL leaves no exit record


def test_state_lives_in_the_tools_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNS_DIR", raising=False)
    spec = importlib.util.spec_from_file_location("detach", SCRIPTS / "detach.py")
    assert spec is not None and spec.loader is not None
    detach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detach)
    pyproject = (SCRIPTS.parent / "pyproject.toml").read_text()
    assert f'\n{detach.tool_name()} = "' in pyproject.split("[project.scripts]")[1]
    assert detach.runs_dir().parts[-2:] == (detach.tool_name(), "runs")


def test_bad_input(runs: Path) -> None:
    assert sh("run_detached.sh", "../x", "true").returncode == 2
    assert sh("run_detached.sh", "nothing").returncode == 2
    assert sh("runs_status.sh", "missing").returncode == 1
    missing = sh("run_detached.sh", "ghost", "no-such-program-xyz")
    assert missing.returncode == 0
    assert wait_for("ghost", "done")["exit_code"] == 127
