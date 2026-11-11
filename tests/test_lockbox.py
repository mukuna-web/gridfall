"""Lockbox discipline and repo hygiene, checked from the source tree (docs/plan.md, Review Focus 5)."""

import hashlib
import json
import os
import re
import subprocess
import unicodedata
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOCKBOX_IDS = ("helene2024", "milton2024")
# Only these may name a lockbox table or extract: the runner that opens it once, the export that waits for it, the
# storm list, the logs, the plan and the frozen record of the one opening.
ALLOWED = {"src/blackout/final.py", "config/storms.yaml", "docs/decision-log.md", "docs/plan.md", "docs/design.md",
           "docs/scorecard.md", "docs/failures.md", "docs/writeup.md", "docs/test-plan.md", "README.md",
           "tests/test_lockbox.py", "tests/test_export.py", "tests/test_model.py", "tests/test_evaluate.py",
           "tests/test_final.py", "tests/test_storms_winds_counties.py", "src/blackout/export.py",
           "src/blackout/storms.py", "src/blackout/model.py", "src/blackout/evaluate.py", "app/README.md",
           "app/src/__fixtures__/milton/README.md", "docs/lockbox_result.json", "docs/lockbox_record.json"}
# LB-45: sha256 of docs/lockbox_result.json, the frozen copy of the one opening's result (2026-11-08 23:55 PST).
FROZEN_RESULT_SHA256 = "db6cb77a81c2a784bfe5107a8fd9668f57db2aa032e51c37a92cba0d346e1965"


def test_lockbox_result_is_frozen():
    """LB-45: the committed record never changes, and the local result it was copied from stays byte-identical."""
    frozen = REPO / "docs/lockbox_result.json"
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FROZEN_RESULT_SHA256
    local = REPO / "data/processed/lockbox_result.json"
    if local.exists():
        assert local.read_bytes() == frozen.read_bytes(), "data/processed/lockbox_result.json differs from the record"


def git_files(*options: str) -> list[str]:
    """What `git ls-files` lists with these options, under the names the files have on disk. git is asked for -z: it
    then writes each name as it is and ends it with a NUL character. Without -z it prints a name that holds a letter
    outside ASCII, a quote or a line break in quotes and with escapes, which is the name of no file."""
    out = subprocess.run(["git", "ls-files", "-z", *options], cwd=REPO, capture_output=True, check=True).stdout
    return [os.fsdecode(name) for name in out.split(b"\0") if name]


def tracked_files() -> list[str]:
    return git_files()


def new_files() -> list[str]:
    """Files git neither tracks nor ignores: what the next `git add` would take in."""
    return [name for name in git_files("--others", "--exclude-standard") if (REPO / name).is_file()]


def in_git_checkout() -> bool:
    """False in a folder git does not manage, such as an unpacked ZIP download, and where git is not installed."""
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO, capture_output=True,
                                text=True, check=False)
    except OSError:
        return False
    return inside.returncode == 0 and inside.stdout.strip() == "true"


# The two scans below ask git which files are tracked. In a folder git does not manage there is no such list, so they
# are skipped there. This is decided once, for the real folder: other tests call the two scans directly, on folders
# of their own (a new, empty repository, or a plain folder with a stand-in for git).
needs_git_checkout = pytest.mark.skipif(
    not in_git_checkout(),
    reason="not a git checkout (an unpacked ZIP download, say): git cannot list the tracked files to scan")


@needs_git_checkout
def test_no_code_or_test_reads_a_lockbox_table_directly():
    pattern = re.compile(r"(county_nights_|eaglei_|predictions_)(helene2024|milton2024)")
    offenders = []
    for path in tracked_files():
        if not path.endswith((".py", ".ts", ".tsx", ".yaml", ".json", ".md", ".sh")) or path in ALLOWED:
            continue
        text = (REPO / path).read_text(errors="ignore")
        if pattern.search(text):
            offenders.append(path)
    assert offenders == [], f"these files name a lockbox table: {offenders}"


def test_tests_never_hardcode_lockbox_official_numbers():
    """Tests use synthetic worlds; a real Helene or Milton outage figure in a test would be a leak."""
    for path in (REPO / "tests").rglob("*.py"):
        text = path.read_text()
        for sid in LOCKBOX_IDS:
            assert f"{sid}.parquet" not in text, f"{path.name} opens a {sid} file"


@needs_git_checkout
def test_secrets_and_data_stay_untracked():
    tracked = set(tracked_files())
    assert ".env" not in tracked
    assert not any(p.startswith(("data/raw/", "data/interim/", "data/processed/")) for p in tracked)
    ignore = (REPO / ".gitignore").read_text()
    for needed in ("data/raw/", "data/interim/", "data/processed/", ".env", "node_modules/"):
        assert needed in ignore
    token_like = re.compile(r"EARTHDATA_TOKEN\s*=\s*[A-Za-z0-9._-]{20,}")
    # New files are read too: a file that fails this scan only once it is tracked fails it one commit too late.
    for path in sorted(tracked | set(new_files())):
        if path.endswith((".py", ".md", ".yaml", ".toml", ".json", ".ts", ".tsx", ".example", ".yml")):
            found = token_like.search((REPO / path).read_text(errors="ignore")) is not None  # the match is not shown
            assert not found, f"{path} holds a token"


# File names git prints in quotes and with escapes unless it is asked for -z: a letter outside ASCII, a quote, a line
# break. Read line by line, such a name is the name of no file, and the scans above would pass the file over.
AWKWARD_NAMES = ("t\u00f6k.md", 'say "hi".md', "two\nlines.md")
MADE_UP = "MADE-UP-not-a-token-0123456789"  # what a planted line holds after the variable's name and an equals sign
NEEDED_IGNORES = "data/raw/\ndata/interim/\ndata/processed/\n.env\nnode_modules/\n"


@pytest.fixture
def empty_repo(tmp_path, monkeypatch) -> Path:
    """A new git repository in REPO's place, with nothing added or committed. git reads its built-in settings only:
    this machine's git settings, its list of ignored names and its GIT_ variables could quote names differently,
    ignore other files or point git at another repository."""
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-settings"))  # where git looks for the user's ignore file
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--quiet", str(repo)], capture_output=True, check=True)
    (repo / ".gitignore").write_text(NEEDED_IGNORES)
    monkeypatch.setitem(globals(), "REPO", repo)
    return repo


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_the_secret_scan_reads_a_new_file_whatever_its_name_holds(name, empty_repo):
    (empty_repo / name).write_text("EARTHDATA_TOKEN=" + MADE_UP + "\n")
    assert [unicodedata.normalize("NFC", listed) for listed in new_files()] == [".gitignore", name]
    with pytest.raises(AssertionError, match="holds a token") as caught:
        test_secrets_and_data_stay_untracked()
    assert MADE_UP not in str(caught.value)
    (empty_repo / name).write_text("EARTHDATA_TOKEN=${{ secrets.EARTHDATA_TOKEN }}\n")  # how a workflow names it
    test_secrets_and_data_stay_untracked()


def test_tracked_and_new_files_are_listed_by_the_names_they_have_on_disk(tmp_path, monkeypatch):
    """git is stood in for here (nothing is tracked in a repository until something is added to it): asked for -z it
    writes each name as it is and ends it with a NUL character, which no file name can hold."""
    names = ["plain.py", *AWKWARD_NAMES]
    asked = []

    def git(cmd, **kwargs):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"".join(os.fsencode(name) + b"\0" for name in names))

    (tmp_path / ".gitignore").write_text(NEEDED_IGNORES)
    for name in names:
        (tmp_path / name).write_text("nothing to find\n")
    monkeypatch.setitem(globals(), "REPO", tmp_path)
    monkeypatch.setattr(subprocess, "run", git)
    assert tracked_files() == names and new_files() == names
    assert asked == [["git", "ls-files", "-z"], ["git", "ls-files", "-z", "--others", "--exclude-standard"]]
    test_secrets_and_data_stay_untracked()
    test_no_code_or_test_reads_a_lockbox_table_directly()
    # a tracked file under such a name is read by both scans
    (tmp_path / AWKWARD_NAMES[0]).write_text("EARTHDATA_TOKEN=" + MADE_UP + " county_nights_" + LOCKBOX_IDS[0])
    with pytest.raises(AssertionError, match="holds a token"):
        test_secrets_and_data_stay_untracked()
    with pytest.raises(AssertionError, match="name a lockbox table"):
        test_no_code_or_test_reads_a_lockbox_table_directly()


FROZEN_TREE_PARAMS = {"max_iter": 300, "learning_rate": 0.05, "min_samples_leaf": 40, "l2_regularization": 1.0,
                      "random_state": 0, "early_stopping": False}
# hybrid._features at 2187e37 ("Model choice"): the corrected darkening, the county's darkening scaled by its own
# calm-night noise (z, log sd), wind band, days since landfall, brightness, moon, view angle and visibility.
FROZEN_FEATURES = ["z", "darker", "log_sd", "wind_band", "days", "log_base_total", "lunar_irradiance",
                   "sensor_zenith", "visible_share"]
FROZEN_WIND_TIMING_FEATURES = ["wind_band", "days"]
FROZEN_RISING = {"z", "darker", "wind_band"}
PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT, OPENING_COMMIT, RECORD_COMMIT = "2f534f9", "2187e37", "7fd2732", "50d572e"
# Those commits are in the development history. Where HEAD does not descend from them, the checks that read the
# history are skipped with this reason; the checks that need no history still run.
NO_HISTORY = ("this checkout does not stand on the development history (a shallow clone, a folder without git, or the "
              "public repository, which starts from one commit)")
# Of the model files, the two that still are, byte for byte, what the recorded run hashed. ranges.py is not among
# them: its module docstring was reworded in two places on 2026-11-10 (decision log).
UNCHANGED_SINCE_THE_RUN = ("hybrid.py", "model.py")
MODEL_FILES = ("src/blackout/hybrid.py", "src/blackout/model.py", "src/blackout/ranges.py")


def tiny_storm_table():
    """One fake main storm, three counties, every night of its window: enough calm nights for county_noise."""
    import numpy as np
    import pandas as pd

    from blackout.storms import Storm

    s = Storm(id="t2020", name="t", atcf_id=None, landfall=date(2020, 9, 10), baseline_start=date(2020, 8, 29),
              baseline_end=date(2020, 9, 7), window_end=date(2020, 9, 14), role="main", states=("FL",))
    rng = np.random.default_rng(0)
    rows = [{"storm_id": s.id, "fips": f"12{c:03d}", "night": night, "status": "ok", "covered": True,
             "pct_darker": rng.normal(0, 0.05), "sensor_zenith": 20.0, "lunar_irradiance": 0.5, "visible_share": 0.95,
             "base_total": 50_000.0, "wind_band": 64, "official_pct_out": 0.0} for c in range(3) for night in s.nights]
    return pd.DataFrame(rows), [s]


def head_descends_from(*commits: str) -> bool:
    """Is every one of these commits in the history of HEAD? False in a shallow clone that stops short of them, in the
    public repository and outside a git checkout. A commit that is only present, for example fetched from the archive
    into another repository, does not count: the checks below are about the history this checkout stands on."""
    try:
        return all(subprocess.run(["git", "merge-base", "--is-ancestor", f"{c}^{{commit}}", "HEAD"], cwd=REPO,
                                  capture_output=True, check=False).returncode == 0 for c in commits)
    except OSError:  # git is not installed
        return False


def test_the_frozen_hybrid_is_the_shipped_hybrid():
    """LB-21: TREE_PARAMS and the feature list are the ones logged in "Model choice", pinned by content, and hybrid.py
    and model.py are the files the recorded run hashed. Where the development history is present: the model files did
    not change between that entry and the opening; a change since needs a decision-log entry."""
    from blackout import hybrid
    from blackout.model import fit_angle_moon

    assert hybrid.TREE_PARAMS == FROZEN_TREE_PARAMS
    assert [*hybrid.SATELLITE, *hybrid.CONTEXT, *hybrid.AUXILIARY] == FROZEN_FEATURES
    assert hybrid.RISING == FROZEN_RISING
    frame, storms = tiny_storm_table()
    correction = fit_angle_moon(frame, storms)
    assert list(hybrid._features(frame, correction, storms, satellite=True).columns) == FROZEN_FEATURES
    assert list(hybrid._features(frame, correction, storms, satellite=False).columns) == FROZEN_WIND_TIMING_FEATURES
    run_hashes = json.loads((REPO / "docs/lockbox_result.json").read_text())["provenance"]["code_sha256_16"]
    for name in UNCHANGED_SINCE_THE_RUN:
        shipped = hashlib.sha256((REPO / "src/blackout" / name).read_bytes()).hexdigest()[:16]
        assert shipped == run_hashes[name], (f"src/blackout/{name} is not the file the recorded run hashed (any "
                                             "change trips this, a reformat or a line-ending conversion included)")
    if not head_descends_from(MODEL_CHOICE_COMMIT, OPENING_COMMIT, RECORD_COMMIT):
        pytest.skip(f"{NO_HISTORY}: HEAD does not descend from the model-choice, opening and record commits")
    unchanged = subprocess.run(["git", "diff", "--quiet", MODEL_CHOICE_COMMIT, OPENING_COMMIT, "--", *MODEL_FILES],
                               cwd=REPO, check=False)
    assert unchanged.returncode == 0, "the model files changed between the model choice and the opening"
    since = subprocess.run(["git", "log", "--format=%h", f"{RECORD_COMMIT}..HEAD", "--", *MODEL_FILES], cwd=REPO,
                           capture_output=True, text=True, check=True).stdout.split()
    if since:
        log = (REPO / "docs/decision-log.md").read_text()
        dated_after = [h for h in re.findall(r"^## (2026-\d\d-\d\d)", log, re.MULTILINE) if h > "2026-11-08"]
        assert dated_after, f"commits {since} touch the frozen model files with no decision-log entry after the opening"


def test_ci_local_runs_the_ci_commands():
    """RH-03: scripts/ci_local.sh runs every `run:` command of .github/workflows/ci.yml, verbatim, and stops on the
    first error."""
    import yaml

    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    commands = [step["run"] for job in workflow["jobs"].values() for step in job["steps"] if "run" in step]
    script_path = REPO / "scripts/ci_local.sh"
    script = script_path.read_text()
    missing = [c for c in commands if c not in script]
    assert commands and missing == [], f"ci.yml commands not in ci_local.sh: {missing}"
    assert "set -euo pipefail" in script
    assert os.access(script_path, os.X_OK), "scripts/ci_local.sh must be executable"


def test_pass_bar_was_committed_before_any_lockbox_score():
    """The decision-log entry carrying the pass bar must predate the lockbox result, if one exists. This reads the
    development history, so it runs only where HEAD descends from the pass-bar commit."""
    if not head_descends_from(PASS_BAR_COMMIT):
        pytest.skip(f"{NO_HISTORY}: HEAD does not descend from the pass-bar commit")
    log = subprocess.run(["git", "log", "--format=%H %s", "--", "docs/decision-log.md"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    assert "pass bar before lockbox" in log
    result = REPO / "data/processed/lockbox_result.json"
    if result.exists():
        bar_time = int(subprocess.run(["git", "log", "-1", "--format=%ct", "--grep=pass bar before lockbox"],
                                      cwd=REPO, capture_output=True, text=True, check=True).stdout.strip())
        assert result.stat().st_mtime > bar_time
