"""notebooks/reproduce_colab.ipynb: its code cells run here against stand-ins for Colab (the secret store, /content
and git), so the checks they make before and after the run are tested like the rest. Offline."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOTEBOOK = json.loads((REPO / "notebooks/reproduce_colab.ipynb").read_text(encoding="utf-8"))
CONTENT = "/content"  # Colab's working folder; the cells are run with a scratch folder in its place
FAKE_TOKEN = "FAKE-earthdata-token-0123456789"  # made up


def token_state() -> str | None:
    """A digest of EARTHDATA_TOKEN, or None when it is not set: enough to see a change, and nothing that a failing
    assertion could print (the variable may hold the developer's real token)."""
    value = os.environ.get("EARTHDATA_TOKEN")
    return None if value is None else hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def earthdata_token_left_as_it_was():
    """Cell 1 writes the token into os.environ, where every later test would find it: once the tests here are done,
    the variable is what it was before them, set or not."""
    before = token_state()
    yield
    assert token_state() == before, "the notebook tests changed EARTHDATA_TOKEN in os.environ and did not undo it"


@pytest.fixture(autouse=True)
def back_in_the_starting_folder(monkeypatch):
    """Cell 2 changes the current directory (to the stand-in for /content): each test ends where it started."""
    monkeypatch.chdir(Path.cwd())


def cell(title: str) -> str:
    """The source of the code cell whose title line starts with `title`."""
    sources = ["".join(c["source"]) for c in NOTEBOOK["cells"] if c["cell_type"] == "code"]
    (source,) = [s for s in sources if s.startswith(f"#@title {title}")]
    return source


def run_cell(title: str, content: Path, **names) -> dict:
    """Run a cell as Python with /content moved to `content`; its shell and magic lines (! and %) are left out."""
    lines = [line for line in cell(title).splitlines() if not line.startswith(("!", "%"))]
    namespace = dict(names)
    exec(compile("\n".join(lines).replace(CONTENT, str(content)), title, "exec"), namespace)  # noqa: S102
    return namespace


class Userdata(types.ModuleType):
    """google.colab.userdata with the real module's three errors; `secrets` maps a name to a value or to an error."""

    class SecretNotFoundError(Exception):
        pass

    class NotebookAccessError(Exception):
        pass

    class TimeoutException(Exception):  # the real module's name for it
        pass

    def __init__(self, secrets: dict):
        super().__init__("google.colab.userdata")
        self.secrets = secrets

    def get(self, name: str) -> str:
        if name not in self.secrets:
            raise self.SecretNotFoundError(name)
        if isinstance(self.secrets[name], type):
            raise self.secrets[name](name)
        return self.secrets[name]


# Short names for two of the errors. The secrets below are passed as keyword arguments, and the repository's secret
# scan (tests/test_lockbox.py) takes the variable's name, an equals sign and 20 or more letters, digits, dots, dashes
# or underscores for a token: written out after the name, an error's dotted name is long enough to be one.
TIMED_OUT, NO_ACCESS = Userdata.TimeoutException, Userdata.NotebookAccessError


def settings(monkeypatch, level: int, **secrets) -> dict:
    """Run cell 1 at `level` with these Colab secrets; returns the cell's names."""
    userdata = Userdata(secrets)
    colab = types.ModuleType("google.colab")
    colab.userdata = userdata
    google = sys.modules.get("google") or types.ModuleType("google")
    for name, module in (("google", google), ("google.colab", colab), ("google.colab.userdata", userdata)):
        monkeypatch.setitem(sys.modules, name, module)
    # Set, then removed: removing a variable that is not set records nothing, and the value the cell writes into
    # os.environ would outlive the test. After the test the variable is what it was before, set or not.
    monkeypatch.setenv("EARTHDATA_TOKEN", "")
    monkeypatch.delenv("EARTHDATA_TOKEN")
    source = cell("1. Settings")
    assert source.count("LEVEL = 1 ") == 1  # the form's default, replaced by the level under test
    source = source.replace("LEVEL = 1 ", f"LEVEL = {level} ")
    namespace = {}
    exec(compile(source, "settings", "exec"), namespace)  # noqa: S102
    return namespace


def test_settings_load_the_secrets_without_printing_them(monkeypatch, capsys):
    names = settings(monkeypatch, 1, EARTHDATA_TOKEN=f" {FAKE_TOKEN}\n", GITHUB_TOKEN="gh-FAKE")
    assert os.environ["EARTHDATA_TOKEN"] == FAKE_TOKEN and names["github_token"] == "gh-FAKE"
    out = capsys.readouterr().out
    assert "level 1; Earthdata token: loaded; GitHub token: loaded" in out and "FAKE" not in out


@pytest.mark.parametrize("value", ["", " \n"])
def test_an_empty_required_secret_stops_the_settings_cell(monkeypatch, value):
    with pytest.raises(SystemExit, match="The secret EARTHDATA_TOKEN is empty"):
        settings(monkeypatch, 1, EARTHDATA_TOKEN=value)
    names = settings(monkeypatch, 0, EARTHDATA_TOKEN=value)  # level 0 needs no token
    assert names["github_token"] is None


def test_an_unanswered_access_prompt_stops_only_for_a_secret_the_level_needs(monkeypatch, capsys):
    names = settings(monkeypatch, 1, EARTHDATA_TOKEN=FAKE_TOKEN, GITHUB_TOKEN=TIMED_OUT)
    assert names["github_token"] is None
    assert "GITHUB_TOKEN: not set or not readable, continuing without it" in capsys.readouterr().out
    settings(monkeypatch, 0, EARTHDATA_TOKEN=TIMED_OUT)
    with pytest.raises(SystemExit, match="answer the access prompt"):
        settings(monkeypatch, 1, EARTHDATA_TOKEN=TIMED_OUT)
    with pytest.raises(SystemExit, match="Add the secret EARTHDATA_TOKEN .*NotebookAccessError"):
        settings(monkeypatch, 2, EARTHDATA_TOKEN=NO_ACCESS)
    with pytest.raises(SystemExit, match="Add the secret EARTHDATA_TOKEN .*SecretNotFoundError"):
        settings(monkeypatch, 1)


def test_the_checkout_is_reused_only_for_the_repository_and_branch_it_was_cloned_from(monkeypatch, tmp_path):
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[0] == "git":
            (Path(cmd[-1]) / ".git").mkdir(parents=True)  # what a clone leaves behind
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    first = {"REPO": "owner/gridfall", "BRANCH": "main", "github_token": None}
    run_cell("2. Get the code", tmp_path, **first)
    dest = tmp_path / "gridfall"
    assert commands[0] == ["git", "clone", "--quiet", "--branch", "main",
                           "https://github.com/owner/gridfall.git", str(dest)]
    assert len(commands) == 4  # the clone, then pip, uv sync and the Python version
    run_cell("2. Get the code", tmp_path, **first)
    assert len(commands) == 7 and [cmd[0] for cmd in commands].count("git") == 1  # run again: no second clone
    for changed in ({**first, "BRANCH": "review-branch"}, {**first, "REPO": "someone-else/a-fork"}):
        with pytest.raises(SystemExit, match="holds owner/gridfall at main, not .* delete it"):
            run_cell("2. Get the code", tmp_path, **changed)
    assert len(commands) == 7


def test_the_checkout_can_be_deleted_and_cloned_again_wherever_the_kernel_was_left(monkeypatch, tmp_path):
    """Deleting the checkout and running cell 2 again is what the cell asks for when REPO or BRANCH changed. Its own
    `%cd` puts the kernel inside the checkout, so once the checkout is deleted the kernel sits in a folder that no
    longer exists. git cannot work from there (exit 128: it cannot read the current directory); nor can this
    stand-in."""
    started_in = []

    def run(cmd, **kwargs):
        try:
            folder = Path(kwargs.get("cwd") or os.getcwd())  # getcwd() fails in a deleted folder, as it does for git
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: Unable to read current working "
                                                                           "directory: No such file or directory")
        assert folder.is_dir(), f"{cmd[0]} was started in {folder}, which does not exist"
        started_in.append(folder)
        if cmd[0] == "git":
            (Path(cmd[-1]) / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def cd_into_the_checkout() -> None:
        os.chdir(dest)  # the cell's `%cd /content/gridfall`, which run_cell leaves out

    monkeypatch.setattr(subprocess, "run", run)
    first = {"REPO": "owner/gridfall", "BRANCH": "main", "github_token": None}
    changed = {**first, "BRANCH": "review-branch"}
    dest = tmp_path / "gridfall"
    run_cell("2. Get the code", tmp_path, **first)
    cd_into_the_checkout()
    # The recovery as the cell words it: BRANCH changed, the cell stops, the checkout is deleted, the cell is run again.
    with pytest.raises(SystemExit, match="delete it .* and run this cell again"):
        run_cell("2. Get the code", tmp_path, **changed)
    shutil.rmtree(dest)  # `!rm -rf /content/gridfall`
    run_cell("2. Get the code", tmp_path, **changed)
    assert (dest / ".git" / "cloned-from").read_text() == "owner/gridfall at review-branch"
    # The same with the checkout deleted first, from inside it: the cell starts in a folder that is gone.
    cd_into_the_checkout()
    shutil.rmtree(dest)
    with pytest.raises(FileNotFoundError):
        os.getcwd()
    run_cell("2. Get the code", tmp_path, **first)
    assert (dest / ".git" / "cloned-from").read_text() == "owner/gridfall at main"
    assert len(started_in) == 12 and started_in[8].samefile(tmp_path)  # three clones of four commands, from /content
    assert Path.cwd().samefile(tmp_path)  # and the kernel is in a real folder again


def test_a_token_is_passed_to_git_through_the_environment_only(monkeypatch, tmp_path):
    seen = {}

    def run(cmd, **kwargs):
        if cmd[0] == "git":
            seen.update(cmd=cmd, env=kwargs["env"])
            (Path(cmd[-1]) / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    names = run_cell("2. Get the code", tmp_path, REPO="owner/private", BRANCH="main", github_token="gh-FAKE")
    assert seen["env"]["GIT_TOKEN"] == "gh-FAKE" and "gh-FAKE" not in " ".join(seen["cmd"])
    assert names["github_token"] is None


def test_the_run_cell_removes_an_older_report_first():
    lines = cell("3. Reproduce").splitlines()
    report = f"{CONTENT}/reproduce-report.json"
    assert lines.index(f"!rm -f {report}") < lines.index(
        f"!uv run python -I scripts/reproduce.py --level {{LEVEL}} --report {report}")


def report_cell(tmp_path: Path, capsys, level: int = 1, **report) -> str:
    """What cell 4 prints for this report (written to the scratch /content first)."""
    payload = {"level": 1, "platform": "colab", "build": None, **report}
    (tmp_path / "reproduce-report.json").write_text(json.dumps(payload))
    run_cell("4. The report", tmp_path, LEVEL=level)
    return capsys.readouterr().out


def check(name: str, passed: bool) -> dict:
    return {"name": name, "passed": passed, "detail": "stub", "seconds": 0.1}


def test_the_report_cell_prints_pass_only_for_a_complete_run_at_this_level(tmp_path, capsys):
    passing = [check("unit tests", True), check("Earthdata token", True)]
    out = report_cell(tmp_path, capsys, complete=True, passed=True, checks=passing)
    assert out.startswith("PASS - level 1 on colab") and out.count("[PASS]") == 2
    # A run that died after its first checks: the report an older script left behind said passed: true with no
    # "complete" at all, and the one written now says complete: false and passed: false. Neither is a pass.
    for half_done in ({"passed": True}, {"complete": False, "passed": False}):
        out = report_cell(tmp_path, capsys, checks=passing, **half_done)
        assert out.startswith("INCOMPLETE") and "PASS - level" not in out
    out = report_cell(tmp_path, capsys, complete=True, passed=False, checks=[*passing, check("comparison", False)])
    assert out.startswith("FAIL - level 1") and "[FAIL] comparison" in out
    out = report_cell(tmp_path, capsys, complete=False, passed=False, checks=[check("run aborted", False)])
    assert out.startswith("FAIL - level 1")
    with pytest.raises(SystemExit, match="from a level 1 run, not level 2"):
        report_cell(tmp_path, capsys, level=2, complete=True, passed=True, checks=passing)


def test_the_report_cell_lists_failed_downloads_and_stops_when_there_is_no_report(tmp_path, capsys):
    out = report_cell(tmp_path, capsys, complete=True, passed=False, checks=[check("satellite downloads", False)],
                      build={"problems": ["A2 2022-09-29: OSError: 503"]})
    assert "satellite files that could not be read" in out and "    A2 2022-09-29: OSError: 503" in out
    (tmp_path / "reproduce-report.json").unlink()
    with pytest.raises(SystemExit, match="no report was written"):
        run_cell("4. The report", tmp_path, LEVEL=1)
