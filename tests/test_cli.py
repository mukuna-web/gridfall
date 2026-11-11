"""The command line dispatches to the right step, skips tables that already exist, and refuses a second opening."""

import hashlib
import json
import sys
import types

import pytest

from blackout import cli


def test_build_extract_only(monkeypatch, tmp_path):
    from blackout import table

    seen = []
    monkeypatch.setattr(table, "extract_eaglei", lambda storm: seen.append(storm.id) or tmp_path / f"{storm.id}.parquet")
    assert cli.main(["build", "--storm", "ian2022", "--extract-only"]) == 0
    assert seen == ["ian2022"]


def test_build_skips_existing_table(monkeypatch, tmp_path):
    from blackout import table

    existing = tmp_path / "t.parquet"
    existing.write_bytes(b"x")
    monkeypatch.setattr(table, "table_path", lambda storm, satellite="VNP46A2": existing)
    monkeypatch.setattr(table, "build_storm", lambda *a, **k: pytest.fail("must not rebuild"))
    assert cli.main(["build", "--storm", "ian2022"]) == 0
    built = []
    monkeypatch.setattr(table, "build_storm", lambda storm, satellite: built.append((storm.id, satellite)))
    assert cli.main(["build", "--storm", "ian2022", "--force", "--satellite", "VJ146A2"]) == 0
    assert built == [("ian2022", "VJ146A2")]


class Opened(RuntimeError):
    pass


def fake_final(calls: list, opened: bool) -> types.SimpleNamespace:
    """A stand-in for blackout.final: refuses without a reason once opened, else returns a small result."""
    def run_final(processed=None, reopen_reason=None):
        if opened and reopen_reason is None:
            raise Opened("lockbox_result.json exists: pass --reopen \"<reason>\" to look again (D-12)")
        calls.append(("lockbox", reopen_reason))
        result = {"verdict": "pass", "pass_bar": {"lock2024": {60: {"passes": True}}}}
        if reopen_reason is not None:
            result["reopen"] = {"reason": reopen_reason, "result": "lockbox_result_20261109T100000Z.json",
                                "outputs": "reopen_20261109T100000Z"}
        return result

    return types.SimpleNamespace(run_final=run_final, LockboxOpenedError=Opened)


def test_evaluate_export_and_lockbox_dispatch(monkeypatch, capsys):
    calls = []
    monkeypatch.setitem(sys.modules, "blackout.evaluate",
                        types.SimpleNamespace(write_scorecard=lambda: calls.append("evaluate")))
    monkeypatch.setitem(sys.modules, "blackout.export", types.SimpleNamespace(
        export_sample=lambda scorecard=None: calls.append("sample"),
        export_storm=lambda storm, scorecard=None: calls.append(storm)))
    monkeypatch.setitem(sys.modules, "blackout.final", fake_final(calls, opened=False))
    assert cli.main(["evaluate"]) == 0
    assert cli.main(["export", "--sample"]) == 0
    assert cli.main(["export", "--storm", "milton2024"]) == 0
    assert cli.main(["lockbox"]) == 0
    assert calls == ["evaluate", "sample", "milton2024", ("lockbox", None), "evaluate"]  # lockbox re-renders the scorecard
    assert '"verdict": "pass"' in capsys.readouterr().out


def test_lockbox_refuses_a_second_opening_and_reopens_with_a_reason(monkeypatch, capsys):
    """LB-39 (CLI half): once opened, `blackout lockbox` exits non-zero and says why; `--reopen "<reason>"` runs
    again into a new file and does not re-render the scorecard."""
    calls = []
    monkeypatch.setitem(sys.modules, "blackout.evaluate",
                        types.SimpleNamespace(write_scorecard=lambda: calls.append("evaluate")))
    monkeypatch.setitem(sys.modules, "blackout.final", fake_final(calls, opened=True))
    assert cli.main(["lockbox"]) == 1
    captured = capsys.readouterr()
    assert "refused" in captured.err and "--reopen" in captured.err and calls == []
    assert captured.out == ""
    assert cli.main(["lockbox", "--reopen", "re-check the drop rule"]) == 0
    captured = capsys.readouterr()
    assert calls == [("lockbox", "re-check the drop rule")]  # no write_scorecard: the record is untouched
    printed = json.loads(captured.out)
    assert printed["reopen"]["result"] == "lockbox_result_20261109T100000Z.json"
    assert "decision-log" in captured.err


def test_lockbox_blank_reopen_reason_is_refused_before_anything_runs(monkeypatch, capsys):
    """`--reopen "  "` is not a reason: the command refuses with a message and exit 1, and never calls run_final."""
    calls = []
    monkeypatch.setitem(sys.modules, "blackout.final", fake_final(calls, opened=True))
    assert cli.main(["lockbox", "--reopen", "   "]) == 1
    captured = capsys.readouterr()
    assert "refused" in captured.err and "reason" in captured.err and captured.out == ""
    assert calls == []


def test_lockbox_ceremony_end_to_end(monkeypatch, tmp_path, capsys):
    """LB-39: against a synthetic world in tmp, `blackout lockbox` opens the lockbox once and writes the marker, the
    result, the score table and predictions for every storm; the second call exits 1, prints the reopen instructions
    and changes no file; `--reopen "<reason>"` writes a new result beside the first and re-renders nothing."""
    from test_final import STORMS, stub_fits, synthetic_processed

    from blackout import evaluate

    synthetic_processed(monkeypatch, tmp_path)  # table.PROCESSED -> tmp; run_final() resolves it at call time
    stub_fits(monkeypatch)
    rendered = []
    monkeypatch.setattr(evaluate, "write_scorecard", lambda: rendered.append("scorecard"))

    def hashes() -> dict[str, str]:
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir() if p.is_file()}

    assert cli.main(["lockbox"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["verdict"] in ("pass", "partial", "fail") and rendered == ["scorecard"]
    opened = hashes()
    assert {"lockbox_opened.json", "lockbox_result.json", "scorecard_final.parquet"} <= set(opened)
    assert all(f"predictions_{s.id}.parquet" in opened for s in STORMS)

    assert cli.main(["lockbox"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "refused" in captured.err and "--reopen" in captured.err
    assert hashes() == opened, "a refused run must change no file"
    assert rendered == ["scorecard"], "a refused run renders nothing"

    assert cli.main(["lockbox", "--reopen", "re-check the drop rule after the fix"]) == 0
    captured = capsys.readouterr()
    reopened = json.loads(captured.out)["reopen"]
    assert reopened["reason"] == "re-check the drop rule after the fix" and "decision-log" in captured.err
    assert hashes() == {**opened, reopened["result"]: hashes()[reopened["result"]]}, "the first files are untouched"
    assert (tmp_path / reopened["outputs"] / "predictions_lock2024.parquet").exists()
    assert rendered == ["scorecard"], "a reopen does not re-render the scorecard"


def test_unknown_storm_fails():
    with pytest.raises(KeyError):
        cli.main(["build", "--storm", "nope1999"])


def test_build_all_continues_after_a_failed_storm(monkeypatch, tmp_path):
    import httpx

    from blackout import table

    monkeypatch.setattr(table, "table_path", lambda storm, satellite="VNP46A2": tmp_path / f"{storm.id}.parquet")
    built = []

    def flaky(storm, satellite):
        if storm.id == "florence2018":
            raise httpx.ConnectError("boom")
        built.append(storm.id)

    monkeypatch.setattr(table, "build_storm", flaky)
    assert cli.main(["build", "--all"]) == 1
    assert "florence2018" not in built and "uri2021" in built
