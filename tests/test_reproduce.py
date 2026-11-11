"""scripts/reproduce.py: the comparisons that decide a pass, on the committed sample, and the run around them: what
the report says when a run is cut short, what never reaches it, and what stops a rebuild. At the end, what
docs/reproduce/plan.md says of the test suite and of the fingerprint. All offline."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

import blackout.counties
import blackout.laads
import blackout.table as table_mod

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reproduce", REPO / "scripts/reproduce.py")
reproduce = importlib.util.module_from_spec(SPEC)
sys.modules["reproduce"] = reproduce  # dataclasses resolve annotations through sys.modules
SPEC.loader.exec_module(reproduce)
SAMPLE = pd.read_parquet(REPO / "data/sample/county_nights_ian_sample.parquet")
FP = reproduce.fingerprint(SAMPLE)
CHARLOTTE = "12015"
FAKE_TOKEN = "FAKE-earthdata-token-0123456789"  # made up: no test may find it in a report, a summary or the output
STAGES = ("level0", "ensure_reference", "ensure_token", "ensure_inputs", "run_level")  # main() runs them in this order
# Columns whose values differ between Charlotte and Collier, so moving them from one county to the other is a change.
MOVABLE = ("visible_share", "base_total", "sensor_zenith", "lunar_irradiance", "official_customers_out",
           "official_customers_out_30", "official_customers_out_90", "official_pct_out", "official_pct_out_30",
           "official_pct_out_90", "pass_utc", "customers", "housing_units", "wind_band")


def test_sample_matches_itself():
    ok, detail = reproduce.compare_tables(SAMPLE.copy(), SAMPLE)
    assert ok and "165 county-nights" in detail


def test_small_float_noise_is_tolerated_but_a_wrong_value_is_not():
    noisy = SAMPLE.copy()
    noisy["pct_darker"] = noisy["pct_darker"] + 1e-7
    assert reproduce.compare_tables(noisy, SAMPLE)[0]
    wrong = SAMPLE.copy()
    idx = wrong.index[wrong["status"] == "ok"][0]
    wrong.loc[idx, "pct_darker"] = wrong.loc[idx, "pct_darker"] + 0.01
    ok, detail = reproduce.compare_tables(wrong, SAMPLE)
    assert not ok and "pct_darker: 1 rows differ" in detail


def test_official_counts_must_match_exactly():
    off = SAMPLE.copy()
    idx = off["official_customers_out"].first_valid_index()
    off.loc[idx, "official_customers_out"] += 0.5
    ok, detail = reproduce.compare_tables(off, SAMPLE)
    assert not ok and "official_customers_out" in detail


def test_status_and_row_set_are_checked():
    flipped = SAMPLE.copy()
    flipped.loc[flipped.index[0], "status"] = "cant_see" if flipped.loc[flipped.index[0], "status"] == "ok" else "ok"
    assert not reproduce.compare_tables(flipped, SAMPLE)[0]
    ok, detail = reproduce.compare_tables(SAMPLE.iloc[:-1], SAMPLE)
    assert not ok and "different county-nights" in detail and "missing ['12071 2022-10-19']" in detail


def test_pass_utc_shift_and_missing_are_caught():
    shifted = SAMPLE.assign(pass_utc=SAMPLE["pass_utc"] + pd.Timedelta(seconds=2))
    ok, detail = reproduce.compare_tables(shifted, SAMPLE)
    assert not ok and "pass_utc: 165 rows" in detail
    assert reproduce.compare_tables(SAMPLE.assign(pass_utc=SAMPLE["pass_utc"] + pd.Timedelta(milliseconds=500)),
                                    SAMPLE)[0]
    one_missing = SAMPLE.copy()
    one_missing.loc[one_missing.index[0], "pass_utc"] = pd.NaT
    ok, detail = reproduce.compare_tables(one_missing, SAMPLE)
    assert not ok and "pass_utc: 1 rows" in detail


def changed_in(column: str) -> pd.DataFrame:
    """The sample with `column` changed in one row, the first `ok` one, where every column holds a value."""
    table = SAMPLE.copy()
    row = table.index[table["status"] == "ok"][0]
    value = table.loc[row, column]
    if column == "night":
        table.loc[row, column] = value + timedelta(days=400)
    elif column == "pass_utc":
        table.loc[row, column] = value + pd.Timedelta(minutes=5)
    elif isinstance(value, (bool, np.bool_)):
        table.loc[row, column] = not value
    elif isinstance(value, str):
        table.loc[row, column] = "99999" if column == "fips" else value + "x"
    else:
        table.loc[row, column] = value + 2  # more than the widest tolerance: 1.0, on the level-2 sums of base_total
    return table


@pytest.mark.parametrize("column", table_mod.TABLE_COLUMNS)
def test_level_1_notices_a_change_in_every_column_of_the_table(column):
    ok, detail = reproduce.compare_tables(changed_in(column), SAMPLE)
    assert not ok and (f"{column}: 1 rows" in detail or "different county-nights" in detail), detail


def test_level_1_needs_exactly_the_columns_it_compares_on_both_sides():
    assert set(table_mod.TABLE_COLUMNS) == {*reproduce.KEY, *reproduce.EXACT, "pass_utc", *reproduce.TOLERANCES}
    for dropped in ("storm_id", "covered", "official_pct_out_30", "official_pct_out_90"):
        ok, detail = reproduce.compare_tables(SAMPLE.drop(columns=dropped), SAMPLE)
        assert not ok and "the rebuilt table's columns" in detail and f"missing ['{dropped}']" in detail
    ok, detail = reproduce.compare_tables(SAMPLE.assign(extra=1), SAMPLE)
    assert not ok and "unexpected ['extra']" in detail
    ok, detail = reproduce.compare_tables(SAMPLE.drop(columns="covered"), SAMPLE.drop(columns="covered"))
    assert not ok and "missing ['covered']" in detail  # absent on both sides is still a column nobody compared


@pytest.mark.parametrize("column", table_mod.TABLE_COLUMNS)
def test_level_2_notices_a_change_in_every_column_of_the_table(column):
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(changed_in(column)), FP)
    assert not ok, detail


def test_int_fips_and_datetime_nights_are_normalised():
    drifted = SAMPLE.assign(fips=SAMPLE["fips"].astype(int), night=pd.to_datetime(SAMPLE["night"]))
    assert reproduce.compare_tables(drifted, SAMPLE)[0]
    fp = reproduce.fingerprint(drifted)
    assert fp["lee_county"]["night"] == FP["lee_county"]["night"] and fp["per_county"].keys() == FP["per_county"].keys()
    assert reproduce.compare_fingerprints(fp, FP)[0]


def test_fingerprint_round_trip_and_detection():
    assert FP["rows"] == 165 and FP["counties"] == 3 and len(FP["nights"]) == 55 and len(FP["per_county"]) == 3
    lee = FP["lee_county"]
    assert lee["pct_darker"][lee["night"].index("2022-09-29")] == pytest.approx(0.760785, abs=1e-5)
    assert FP["wind_band_counts"] == {"50": 1, "64": 2} and FP["coverage_by_state"] == {"12": 0.98}
    assert reproduce.compare_fingerprints(json.loads(json.dumps(FP)), FP)[0]
    changed = SAMPLE.copy()
    changed.loc[changed.index[changed["status"] == "ok"][3], "pct_darker"] += 0.05
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(changed), FP)
    assert not ok and "sum_pct_darker" in detail


@pytest.mark.parametrize("column, delta", [("wind_band", 30), ("customers", 1000), ("housing_units", 100),
                                           ("visible_share", 0.2), ("sensor_zenith", 10), ("lunar_irradiance", 5),
                                           ("coverage", -0.5), ("official_customers_out_30", 1),
                                           ("official_customers_out_90", 1), ("base_total", 5000)])
def test_fingerprint_catches_a_change_in_every_column(column, delta):
    changed = SAMPLE.copy()
    rows = changed["fips"] == CHARLOTTE
    changed.loc[rows, column] = changed.loc[rows, column] + delta
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(changed), FP)
    assert not ok, detail


def test_fingerprint_catches_pass_times_formula_passes_and_swaps_between_counties():
    shifted = SAMPLE.assign(pass_utc=SAMPLE["pass_utc"] + pd.Timedelta(hours=3))
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(shifted), FP)
    assert not ok and "sum_pass_seconds" in detail
    formula = SAMPLE.copy()
    formula.loc[formula.index[0], "pass_source"] = "formula"
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(formula), FP)
    assert not ok and "formula_passes" in detail
    swapped = SAMPLE.copy()
    for _night, part in swapped.groupby("night"):
        others = part[(part["fips"] != reproduce.LEE) & (part["status"] == "ok")]
        if len(others) == 2 and others["pct_darker"].iloc[0] != others["pct_darker"].iloc[1]:
            swapped.loc[others.index, "pct_darker"] = others["pct_darker"].to_numpy()[::-1]
            break
    else:
        pytest.fail("the sample has no night with two ok non-Lee counties")
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(swapped), FP)
    assert not ok and "county 120" in detail and "sum_pct_darker" not in detail


def moved_between_counties(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """`column` handed round among the counties other than Lee, night by night: every county gets a neighbour's value
    and no night's sum changes."""
    out = table.reset_index(drop=True)
    for _night, part in out[out["fips"] != reproduce.LEE].groupby("night"):
        rows = part.index.to_numpy()
        out.loc[rows, column] = out.loc[np.roll(rows, 1), column].array
    return out


def night_problems(detail: str) -> list[str]:
    return [problem for problem in detail.split("; ") if problem.startswith("20")]  # they begin with the date


@pytest.mark.parametrize("column", MOVABLE)
def test_fingerprint_catches_a_column_moved_to_other_counties_on_the_same_nights(column):
    moved = moved_between_counties(SAMPLE, column)
    assert not moved[column].equals(SAMPLE[column])
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(moved), FP)
    assert not ok and "over its nights" in detail and not night_problems(detail), detail


def test_fingerprint_catches_passes_moved_by_a_whole_day():
    moved = SAMPLE.assign(pass_utc=SAMPLE["pass_utc"] + pd.Timedelta(days=1))
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(moved), FP)
    assert not ok and reproduce.NIGHT_TO_PASS in detail and not night_problems(detail)


def test_a_fingerprint_file_without_the_county_sums_fails():
    older = {key: value for key, value in FP.items() if key != "county_sums"}
    ok, detail = reproduce.compare_fingerprints(FP, older)
    assert not ok and "county_sums" in detail
    fewer = {**FP, "county_sums": {key: value for key, value in FP["county_sums"].items() if key != "customers"}}
    assert not reproduce.compare_fingerprints(FP, fewer)[0]


# --- a missing value is not a zero: the counts of present values -------------------------------------------------

NEW_KEYS = ("present_per_night", "present_per_county")
A_NIGHT = "2022-10-18"  # Charlotte County's last night in the sample that the satellite could not see


def with_a_zero_and_with_a_gap(column: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The sample twice: with a zero in `column` on one of Charlotte County's nights, and with no value there. The
    night is one the satellite could not see (its pct_darker is in no total) and not the county's first row (which
    supplies the per-county inputs), so every sum in the fingerprint is the same for the two tables."""
    row = SAMPLE.index[(SAMPLE["fips"] == CHARLOTTE) & (SAMPLE["status"] == "cant_see")][-1]
    assert str(SAMPLE.loc[row, "night"]) == A_NIGHT and row != SAMPLE.index[SAMPLE["fips"] == CHARLOTTE][0]
    if column == "pass_utc":
        base, zero, gap = SAMPLE, pd.Timestamp(A_NIGHT, tz="UTC"), pd.NaT  # a pass at 00:00 adds no seconds
    elif column == "covered":
        base, zero, gap = SAMPLE.astype({column: "boolean"}), False, pd.NA
    else:
        base, zero, gap = SAMPLE.astype({column: float}), 0.0, np.nan
    tables = []
    for value in (zero, gap):
        table = base.copy()
        table.loc[row, column] = value
        tables.append(table)
    return tables[0], tables[1]


def test_every_column_a_total_is_taken_of_is_counted():
    per_night = {name.removeprefix("sum_") for name in reproduce.NIGHT_SUM_TOLERANCES}
    of_rows = {"cant_see", "not_measurable", "formula_passes"}  # counts of rows by status and pass source: no column
    per_county = set(reproduce.COUNTY_SUM_TOLERANCES) - of_rows
    assert per_night | per_county | {"pass_utc"} == set(reproduce.PRESENT)  # the pass times are summed as seconds
    assert len(reproduce.PRESENT) == 17 and set(reproduce.PRESENT) <= set(table_mod.TABLE_COLUMNS)


def test_the_fingerprint_counts_the_values_present_per_night_and_per_county():
    per_night, per_county = FP["present_per_night"], FP["present_per_county"]
    assert set(per_night) == {"night", *reproduce.PRESENT} and set(per_county) == {"fips", *reproduce.PRESENT}
    assert per_night["night"] == list(FP["nights"]) and per_county["fips"] == ["12015", "12021", "12071"]
    assert per_county["pct_darker"] == [30, 31, 32] and sum(per_night["pct_darker"]) == FP["status_counts"]["ok"]
    # one number where every night, or every county, holds the same count: it keeps the committed file small
    assert all(per_night[column] == 3 and per_county[column] == 55
               for column in reproduce.PRESENT if column != "pct_darker")
    assert list(FP)[-2:] == list(NEW_KEYS)  # added after the keys the fingerprint already had


@pytest.mark.parametrize("column", reproduce.PRESENT)
def test_level_2_tells_a_missing_value_from_a_zero_in_every_summed_column(column):
    zero, gap = with_a_zero_and_with_a_gap(column)
    held = int(gap.loc[gap["fips"] == CHARLOTTE, column].notna().sum())
    with_zero, with_gap = reproduce.fingerprint(zero), reproduce.fingerprint(gap)
    assert all(with_zero[key] == with_gap[key] for key in FP if key not in NEW_KEYS)  # no total tells them apart
    for built, committed, counts in ((with_gap, with_zero, f"{held} values present vs {held + 1}"),
                                     (with_zero, with_gap, f"{held + 1} values present vs {held}")):
        ok, detail = reproduce.compare_fingerprints(built, committed)
        assert not ok and f"county {CHARLOTTE} {column}: {counts}" in detail, detail
        assert f"{A_NIGHT} {column}: " in detail and detail.count("values present") == 2, detail


def test_a_fingerprint_file_without_the_counts_of_present_values_fails():
    older = {key: value for key, value in FP.items() if key not in NEW_KEYS}  # the file as it was before the counts
    ok, detail = reproduce.compare_fingerprints(FP, older)
    assert not ok and "--fingerprint" in detail
    for key in NEW_KEYS:
        assert f"{key}: the committed fingerprint has no counts of present values" in detail
        ok, detail_one = reproduce.compare_fingerprints(FP, {name: value for name, value in FP.items() if name != key})
        assert not ok and detail_one.count("has no counts of present values") == 1
    fewer = {**FP, "present_per_county": {key: value for key, value in FP["present_per_county"].items()
                                          if key != "customers"}}
    ok, detail = reproduce.compare_fingerprints(FP, fewer)
    assert not ok and "present_per_county: other columns, nights or counties" in detail


def test_fingerprint_catches_lee_status_and_official_changes():
    lee_rows = SAMPLE["fips"] == reproduce.LEE
    official = SAMPLE.copy()
    first_official = official.index[lee_rows & official["official_customers_out"].notna()][0]
    official.loc[first_official, "official_customers_out"] += 0.5
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(official), FP)
    assert not ok and "Lee County: official customers out differ" in detail
    flipped = SAMPLE.copy()
    flipped.loc[flipped.index[lee_rows & (flipped["status"] == "ok")][0], "status"] = "cant_see"
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(flipped), FP)
    assert not ok and "Lee County: nights or statuses differ" in detail


def full_ian_table() -> pd.DataFrame:
    table = REPO / "data/processed/county_nights_ian2022.parquet"
    if not table.exists():
        pytest.skip("the full Ian table is not built here")
    return pd.read_parquet(table)


def test_fingerprint_file_is_current_with_the_full_table():
    committed = json.loads((REPO / "docs/reproduce/ian2022_fingerprint.json").read_text())
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(full_ian_table()), committed)
    assert ok, detail


@pytest.mark.parametrize("column", MOVABLE)
def test_committed_fingerprint_catches_a_column_moved_between_the_504_other_counties(column):
    committed = json.loads((REPO / "docs/reproduce/ian2022_fingerprint.json").read_text())
    moved = moved_between_counties(full_ian_table(), column)
    ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(moved), committed)
    assert not ok and "county " in detail and not night_problems(detail), detail


def test_committed_fingerprint_tells_a_missing_value_from_a_zero_outside_lee_county():
    """One cell of the full table changed, in a county that is not Lee: an official count of 0 that goes missing, a
    missing one that becomes 0, and a 0 for the darkening on a night the satellite could not see. No sum moves."""
    committed = json.loads((REPO / "docs/reproduce/ian2022_fingerprint.json").read_text())
    table = full_ian_table()
    others = table["fips"] != reproduce.LEE
    a_zero = table.index[others & (table["official_customers_out"] == 0)][0]
    a_gap = table.index[others & table["official_customers_out_30"].isna()][0]
    unseen = table.index[others & table["pct_darker"].isna()][0]
    for row, column, value in ((a_zero, "official_customers_out", np.nan), (a_gap, "official_customers_out_30", 0.0),
                               (unseen, "pct_darker", 0.0)):
        changed = table.copy()
        changed.loc[row, column] = value
        ok, detail = reproduce.compare_fingerprints(reproduce.fingerprint(changed), committed)
        assert not ok and f"county {table.loc[row, 'fips']} {column}: " in detail, detail
        assert f"{table.loc[row, 'night']} {column}: " in detail and detail.count("values present") == 2, detail


def test_nan_handling_in_compare():
    a = SAMPLE.copy()
    assert np.isnan(a.loc[a["status"] != "ok", "pct_darker"]).all()
    assert reproduce.compare_tables(a, SAMPLE)[0]


def test_record_check_needs_the_hash_the_file_name_and_a_known_verdict():
    frozen = {"verdict": "fail", "satellite_test": {"verdict": "fail"}}
    good = {"result_file": "docs/lockbox_result.json", "result_sha256": "a" * 64, "uv_lock_sha256": "c" * 64}
    ok, detail = reproduce.record_check(frozen, good, "a" * 64)
    assert ok and "verdict 'fail'" in detail
    ok, detail = reproduce.record_check(frozen, {"result_file": "docs/lockbox_result.json", "uv_lock_sha256": "c" * 64},
                                        "a" * 64)
    assert not ok and "no result_sha256" in detail
    assert not reproduce.record_check(frozen, {**good, "result_sha256": "b" * 64}, "a" * 64)[0]
    assert not reproduce.record_check(frozen, {**good, "result_file": "elsewhere.json"}, "a" * 64)[0]
    assert not reproduce.record_check({"verdict": "maybe"}, good, "a" * 64)[0]


def test_platform_name(monkeypatch):
    for var in ("COLAB_RELEASE_TAG", "COLAB_GPU", "GITHUB_ACTIONS"):
        monkeypatch.delenv(var, raising=False)
    assert reproduce.platform_name() == "local"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert reproduce.platform_name() == "github-actions"
    monkeypatch.setenv("COLAB_GPU", "")  # Colab exports it empty on CPU runtimes
    assert reproduce.platform_name() == "colab"


# --- the report ------------------------------------------------------------------------------------------------------

def test_report_is_rewritten_after_every_check_and_redacts_signed_urls(tmp_path, monkeypatch):
    path = tmp_path / "out" / "report.json"
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local", path)
    report.add("first", True, "fine")
    assert len(json.loads(path.read_text())["checks"]) == 1
    report.add("second", False, "403 for url 'https://d1.cloudfront.net/VNP46A2/x.h5?Signature=abc&Key-Pair-Id=k'")
    payload = json.loads(path.read_text())
    assert not payload["passed"] and payload["build"] is None
    assert payload["checks"][1]["detail"] == "403 for url 'https://d1.cloudfront.net/VNP46A2/x.h5?<redacted>'"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    reproduce.write_step_summary(report)
    assert "## reproduce level 1: FAIL" in summary.read_text() and "| second | FAIL |" in summary.read_text()


def test_a_report_is_a_pass_only_once_the_run_is_complete(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    report = reproduce.Report(0, "2026-01-01T00:00:00+00:00", "local", path)
    assert report.verdict == "INCOMPLETE" and not report.passed
    report.add("only check", True, "fine")
    on_disk = json.loads(path.read_text())
    assert report.clean and on_disk["passed"] is False and on_disk["complete"] is False
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    reproduce.write_step_summary(report)
    assert "## reproduce level 0: INCOMPLETE" in summary.read_text()
    report.complete = True
    report.save()
    assert report.verdict == "PASS" and json.loads(path.read_text())["passed"] is True
    assert not reproduce.Report(0, "2026-01-01T00:00:00+00:00", "local", complete=True).passed  # nothing was checked


def test_redact_drops_url_queries_and_whatever_follows_bearer():
    leaked = f"Illegal header value b'Bearer {FAKE_TOKEN} tail\\n' for 'https://host/path?Signature=abc'"
    assert reproduce.redact(leaked) == "Illegal header value b'Bearer <redacted>' for 'https://host/path?<redacted>'"
    assert reproduce.redact("nothing secret here") == "nothing secret here"


def test_error_text_is_redacted_before_it_is_cut(tmp_path, monkeypatch):
    """A cut that starts inside a signed URL's query would leave redact() nothing to recognise it by."""
    leak = ("503 for url 'https://s3.amazonaws.com/bucket/eaglei.csv?X-Amz-Credential=AKIAFAKE&X-Amz-Signature="
            + "5ec2e7" * 80 + "'")
    monkeypatch.setattr(reproduce, "run", lambda cmd: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=leak))
    monkeypatch.setattr(reproduce, "FROZEN", tmp_path / "absent.json")
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    reproduce.level0(report)
    reproduce.eaglei_check(report)
    assert [check.passed for check in report.checks] == [False] * 4
    assert not any("5ec2e7" in check.detail or "X-Amz" in check.detail for check in report.checks)


# --- the Earthdata token -------------------------------------------------------------------------------------------

def test_a_padded_token_is_trimmed_and_a_broken_one_never_reaches_the_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # no .env here
    probed = []
    monkeypatch.setattr(reproduce, "probe_token", lambda token: probed.append(token) or (True, "accepted"))
    path = tmp_path / "report.json"
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local", path)
    monkeypatch.setenv("EARTHDATA_TOKEN", f" {FAKE_TOKEN}\r\n")
    assert reproduce.ensure_token(report) and probed == [FAKE_TOKEN]
    head, tail = FAKE_TOKEN[:12], FAKE_TOKEN[12:]
    for broken in (f"{head}\n{tail}", f"{head} {tail}", f"{FAKE_TOKEN}\u00e9"):  # line break, space, not ASCII
        monkeypatch.setenv("EARTHDATA_TOKEN", broken)
        assert not reproduce.ensure_token(report)
    assert probed == [FAKE_TOKEN]  # a broken token is never sent anywhere
    everything = path.read_text() + "".join(capsys.readouterr())
    assert head not in everything and everything.count("paste it again") == 6  # three on screen, three in the file


def test_probe_token_never_repeats_a_header_httpx_refused(monkeypatch):
    def refuse(*args):
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {FAKE_TOKEN}\\n'")

    monkeypatch.setattr(blackout.laads, "list_tile_files", refuse)
    ok, detail = reproduce.probe_token(FAKE_TOKEN + "\n")
    assert not ok and "FAKE" not in detail and "paste it again" in detail

    def unreachable(*args):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(blackout.laads, "list_tile_files", unreachable)
    assert reproduce.probe_token(FAKE_TOKEN) == (False, "could not reach NASA: ConnectError: no route to host")
    monkeypatch.setattr(blackout.laads, "list_tile_files", lambda *args: {})
    ok, detail = reproduce.probe_token(FAKE_TOKEN)
    assert not ok and "lists no VNP46A2 h09v06 file" in detail


def probe_with(monkeypatch, status: int, location: str | None = None) -> tuple[bool, str]:
    """probe_token against a stand-in for NASA: the listing names one tile and the one-byte request gets `status`."""
    name = "VNP46A2.A2022272.h09v06.002.2025134023553.h5"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/details"):
            return httpx.Response(200, json={"n_pages": 1, "content": [
                {"name": name, "downloadsLink": f"https://laads.test/{name}", "size": 1, "md5sum": "m"}]})
        if request.url.host == "urs.earthdata.nasa.gov":
            return httpx.Response(200, text="the Earthdata login page")
        return httpx.Response(status, headers={"Location": location} if location else {})

    monkeypatch.setattr(blackout.laads, "client_for", lambda token, timeout=120: httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True))
    return reproduce.probe_token(FAKE_TOKEN)


def test_probe_token_reads_one_byte_and_tells_a_rejected_token_from_a_server_error(monkeypatch):
    ok, detail = probe_with(monkeypatch, 206)
    assert ok and "accepted by Earthdata Cloud (HTTP 206 for one byte of VNP46A2.A2022272.h09v06" in detail
    for status, location in ((401, None), (403, None), (302, "https://urs.earthdata.nasa.gov/oauth/authorize")):
        ok, detail = probe_with(monkeypatch, status, location)
        assert not ok and "rejected by Earthdata" in detail and "tokens expire 60 days" in detail
    ok, detail = probe_with(monkeypatch, 500)
    assert not ok and detail.startswith("unexpected HTTP 500 from data.laadsdaac.earthdatacloud.nasa.gov")
    assert "FAKE" not in detail


# --- the pinned inputs -----------------------------------------------------------------------------------------------

def test_reference_check_names_the_file_a_level_needs(monkeypatch):
    report = reproduce.Report(2, "2026-01-01T00:00:00+00:00", "local")
    assert reproduce.ensure_reference(report, 1) and reproduce.ensure_reference(report, 2)
    monkeypatch.setattr(reproduce, "FINGERPRINT", REPO / "docs/reproduce/absent.json")
    assert not reproduce.ensure_reference(report, 2)
    assert [check.detail for check in report.checks] == [
        "data/sample/county_nights_ian_sample.parquet", "docs/reproduce/ian2022_fingerprint.json",
        "docs/reproduce/absent.json is missing"]


def test_census_check_reports_a_changed_a_missing_and_an_unreachable_file(tmp_path, monkeypatch):
    files = {"shapes.zip": b"county shapes", "housing.dat": b"housing units"}
    for name, body in files.items():
        (tmp_path / name).write_bytes(body)
    pins = {"census": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}}
    monkeypatch.setattr(reproduce, "pinned", lambda: pins)
    monkeypatch.setattr(blackout.counties, "CENSUS", tmp_path)
    monkeypatch.setattr(blackout.counties, "SOURCES", dict.fromkeys(files, "https://census.test"))
    monkeypatch.setattr(blackout.counties, "ensure_census_files", lambda: None)
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    reproduce.census_check(report)
    (tmp_path / "housing.dat").write_bytes(b"a later release")
    reproduce.census_check(report)
    (tmp_path / "shapes.zip").unlink()
    reproduce.census_check(report)

    def unreachable():
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(blackout.counties, "ensure_census_files", unreachable)
    reproduce.census_check(report)
    assert [check.passed for check in report.checks] == [True, False, False, False]
    assert [check.detail for check in report.checks] == [
        "2 files present, hashes match docs/reproduce/inputs.json",
        "['housing.dat'] differ from the hashes in docs/reproduce/inputs.json: an upstream Census file changed",
        "missing ['shapes.zip']", "ConnectError: no route to host"]


def test_hurdat_check_fetches_a_missing_file_and_compares_its_hash(tmp_path, monkeypatch):
    target = tmp_path / "hurdat2-test.txt"
    monkeypatch.setattr(table_mod, "HURDAT", target)
    monkeypatch.setattr(reproduce, "pinned", lambda: {"hurdat2": {"sha256": hashlib.sha256(b"tracks").hexdigest()}})
    served = {"hurdat2-test.txt": b"tracks"}

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=served[name]) if name in served else httpx.Response(404)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    reproduce.hurdat_check(report)  # absent: downloaded, and it is the pinned file
    served.clear()
    reproduce.hurdat_check(report)  # present: not asked for again
    target.write_bytes(b"next spring's file")
    reproduce.hurdat_check(report)
    target.unlink()
    reproduce.hurdat_check(report)  # absent and NHC no longer has it
    assert [check.passed for check in report.checks] == [True, True, False, False] and not target.exists()
    assert "differs from docs/reproduce/inputs.json" in report.checks[2].detail
    assert "HTTPStatusError" in report.checks[3].detail and "a new dated file each spring" in report.checks[3].detail


# --- main(): what runs, what stops it and what the report says afterwards ----------------------------------------

def stage(name: str, passes: bool = True):
    """A stand-in for one of main()'s stages: it records a check under the stage's name and returns the outcome."""
    def run(report, *_):
        report.add(name, passes, "stub")
        return passes
    return run


def stub_stages(monkeypatch, **replaced) -> None:
    for name in STAGES:
        monkeypatch.setattr(reproduce, name, replaced.get(name, stage(name)))


def run_main(tmp_path: Path, *argv: str) -> tuple[int, dict]:
    path = tmp_path / "report.json"
    code = reproduce.main([*argv, "--report", str(path)])
    return code, json.loads(path.read_text())


@pytest.fixture
def summary(tmp_path, monkeypatch) -> Path:
    """The GitHub step summary main() appends to, pointed at a scratch file (CI sets the real one)."""
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    return path


def test_main_level_0_stops_after_the_offline_checks(tmp_path, monkeypatch, summary):
    stub_stages(monkeypatch)
    code, payload = run_main(tmp_path, "--level", "0")
    assert code == 0 and payload["complete"] and payload["passed"]
    assert [check["name"] for check in payload["checks"]] == ["level0"]
    assert "## reproduce level 0: PASS" in summary.read_text()


def test_main_level_1_runs_every_stage_in_order(tmp_path, monkeypatch, summary):
    stub_stages(monkeypatch)
    code, payload = run_main(tmp_path, "--level", "1")
    assert code == 0 and payload["passed"] and [check["name"] for check in payload["checks"]] == list(STAGES)


@pytest.mark.parametrize("failing", STAGES[:4])
def test_a_failed_check_stops_the_run_before_the_rebuild(tmp_path, monkeypatch, summary, failing):
    stub_stages(monkeypatch, **{failing: stage(failing, passes=False)})
    code, payload = run_main(tmp_path, "--level", "2")
    assert code == 1 and payload["complete"] and not payload["passed"]
    assert [check["name"] for check in payload["checks"]] == list(STAGES[:STAGES.index(failing) + 1])
    assert "## reproduce level 2: FAIL" in summary.read_text()


def test_an_exception_is_reported_as_an_aborted_run(tmp_path, monkeypatch, summary, capsys):
    def explode(report):
        report.add("unit tests", True, "ok")
        raise RuntimeError(f"503 for 'https://example.org/tile.h5?Signature=SECRET' with b'Bearer {FAKE_TOKEN}'")

    stub_stages(monkeypatch, level0=explode)
    code, payload = run_main(tmp_path, "--level", "0")
    assert code == 1 and not payload["complete"] and not payload["passed"]
    assert [(c["name"], c["passed"]) for c in payload["checks"]] == [("unit tests", True), ("run aborted", False)]
    assert "## reproduce level 0: FAIL" in summary.read_text()
    everything = json.dumps(payload) + summary.read_text() + "".join(capsys.readouterr())
    assert "SECRET" not in everything and FAKE_TOKEN not in everything and "RuntimeError" in everything


def test_an_interrupted_run_is_incomplete_and_replaces_an_older_pass(tmp_path, monkeypatch, summary):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"level": 0, "complete": True, "passed": True, "checks": []}))  # an earlier run's PASS
    at_start = {}

    def interrupted(report):
        at_start.update(json.loads(path.read_text()))  # what a kill before the first check would leave on disk
        report.add("unit tests", True, "ok")
        raise KeyboardInterrupt

    stub_stages(monkeypatch, level0=interrupted)
    with pytest.raises(KeyboardInterrupt):
        reproduce.main(["--level", "0", "--report", str(path)])
    assert at_start["checks"] == [] and not at_start["passed"] and not at_start["complete"]
    payload = json.loads(path.read_text())
    assert len(payload["checks"]) == 1 and not payload["passed"] and not payload["complete"]
    assert "## reproduce level 0: INCOMPLETE" in summary.read_text() and "| unit tests | PASS |" in summary.read_text()


@pytest.mark.parametrize("scratch", ["data/processed", "data/interim", "docs", "docs/img/new",
                                     "data/sample/../processed"])
def test_a_scratch_folder_inside_data_or_docs_is_refused(scratch, monkeypatch, capsys):
    stub_stages(monkeypatch, level0=lambda report: pytest.fail("the run must not start"))
    with pytest.raises(SystemExit) as stop:
        reproduce.main(["--level", "1", "--scratch", str(REPO / scratch)])
    assert stop.value.code == 2 and "--scratch must be outside data/ and docs/" in capsys.readouterr().err
    monkeypatch.chdir(REPO)
    with pytest.raises(SystemExit):
        reproduce.parse_args(["--scratch", scratch])  # the same folder, given relative to the repo root


def refused(scratch: Path, capsys) -> bool:
    """parse_args stops with the --scratch message for this folder (and with nothing else)."""
    try:
        reproduce.parse_args(["--level", "1", "--scratch", str(scratch)])
    except SystemExit as stop:
        assert stop.code == 2 and "--scratch must be outside data/ and docs/" in capsys.readouterr().err
        return True
    return False


@pytest.mark.parametrize("scratch", ["DATA/processed", "Data/Interim", "DOCS/img", "Docs/new/deeper"])
def test_a_scratch_folder_spelled_in_another_case_is_refused_where_case_does_not_count(scratch, capsys):
    if not (REPO / "DOCS").exists():
        pytest.skip("this file system tells DOCS from docs: these are other folders here")
    assert refused(REPO / scratch, capsys)


def test_a_scratch_folder_reached_through_a_symlink_is_refused(tmp_path, capsys):
    (tmp_path / "figures").symlink_to(REPO / "docs", target_is_directory=True)
    (tmp_path / "tables").symlink_to(REPO / "data" / "sample", target_is_directory=True)
    for scratch in (tmp_path / "figures", tmp_path / "figures" / "img" / "new", tmp_path / "tables"):
        assert refused(scratch, capsys), scratch
    (tmp_path / "real").mkdir()
    (tmp_path / "harmless").symlink_to(tmp_path / "real", target_is_directory=True)
    assert not refused(tmp_path / "harmless", capsys) and not refused(tmp_path / "harmless" / "new", capsys)


def test_a_scratch_folder_is_refused_when_data_itself_is_a_symlink(tmp_path, monkeypatch, capsys):
    """A data folder kept on another disk: the tables are where the link points, under whatever name."""
    repo, disk = tmp_path / "repo", tmp_path / "big-disk"
    (repo / "docs").mkdir(parents=True)
    (disk / "blackout-data" / "processed").mkdir(parents=True)
    (repo / "data").symlink_to(disk / "blackout-data", target_is_directory=True)
    monkeypatch.setattr(reproduce, "REPO", repo)
    for scratch in (repo / "data", repo / "data" / "processed", disk / "blackout-data",
                    disk / "blackout-data" / "processed", disk / "blackout-data" / "new" / "deeper"):
        assert refused(scratch, capsys), scratch
    assert not refused(disk / "elsewhere", capsys) and not refused(repo / "scratch", capsys)


def test_a_scratch_folder_is_refused_when_a_folder_inside_data_or_docs_is_a_symlink(tmp_path, monkeypatch, capsys):
    """One folder down from the test above: data/ and docs/ are real folders, and the folders in them are links to
    another disk. The tables, the extract and the figures are where those links lead, under whatever name."""
    repo, disk = tmp_path / "repo", tmp_path / "big-disk"
    (repo / "docs").mkdir(parents=True)
    (repo / "data" / "sample").mkdir(parents=True)
    for link, target in (("data/processed", "tables"), ("data/interim", "extracts"), ("docs/img", "figures")):
        (disk / target).mkdir(parents=True)
        (repo / link).symlink_to(disk / target, target_is_directory=True)
    unplugged = tmp_path / "unplugged-disk" / "raw"  # where data/raw leads, on a disk that is not there today
    (repo / "data" / "raw").symlink_to(unplugged, target_is_directory=True)
    (disk / "elsewhere").mkdir()
    (repo / "data" / "other").symlink_to(disk / "elsewhere", target_is_directory=True)  # not a folder of the pipeline
    table = repo / "data" / "processed" / "county_nights_ian2022.parquet"
    table.write_bytes(b"the real table")
    monkeypatch.setattr(reproduce, "REPO", repo)
    assert (disk / "tables" / table.name).samefile(table)  # what a rebuild into disk/tables would write over
    for scratch in (repo / "data" / "processed", repo / "data" / "processed" / "new", disk / "tables",
                    disk / "tables" / "new" / "deeper", disk / "extracts", disk / "figures", unplugged,
                    unplugged / "new", repo / "data" / "other"):  # the last: inside data/ as it is typed
        assert refused(scratch, capsys), scratch
    # next to the linked folders, or holding them under names a rebuild does not write to, is outside them
    for scratch in (disk / "elsewhere", disk, repo / "scratch"):
        assert not refused(scratch, capsys), scratch


def test_a_scratch_folder_is_refused_when_its_img_or_interim_folder_is_a_real_one(tmp_path, monkeypatch, capsys):
    """A rebuild also writes into scratch/img and scratch/interim, and first deletes the EAGLE-I extract it finds in
    the latter. Either can be the real folder while the scratch folder itself is outside data/ and docs/: when the
    real folders were moved to another disk together and kept their names, or through a link put into the scratch
    folder (to reuse the extract, say)."""
    repo, moved = tmp_path / "repo", tmp_path / "big-disk" / "blackout"
    (repo / "data").mkdir(parents=True)
    (repo / "docs").mkdir()
    for link, name in (("data/interim", "interim"), ("docs/img", "img")):
        (moved / name).mkdir(parents=True)
        (repo / link).symlink_to(moved / name, target_is_directory=True)
    extract = repo / "data" / "interim" / "eaglei_ian2022.parquet"
    extract.write_bytes(b"the real EAGLE-I extract")
    monkeypatch.setattr(reproduce, "REPO", repo)
    assert reproduce.scratch_folders(moved)[1:] == (moved / "img", moved / "interim")
    assert (moved / "interim" / extract.name).samefile(extract)  # what rebuild() would delete first
    assert refused(moved, capsys)
    for part, real in (("interim", repo / "data" / "interim"), ("img", repo / "docs" / "img")):
        scratch = tmp_path / f"scratch-with-its-{part}-linked"
        scratch.mkdir()
        (scratch / part).symlink_to(real, target_is_directory=True)
        assert refused(scratch, capsys), scratch
    harmless = tmp_path / "scratch-with-links-of-its-own"
    (harmless / "kept-elsewhere").mkdir(parents=True)
    for part in ("img", "interim"):
        (harmless / part).symlink_to(harmless / "kept-elsewhere", target_is_directory=True)
    assert not refused(harmless, capsys) and not refused(moved.parent, capsys)
    stub_stages(monkeypatch, level0=lambda report: pytest.fail("the run must not start"))
    with pytest.raises(SystemExit) as stop:
        reproduce.main(["--level", "1", "--scratch", str(moved)])
    assert stop.value.code == 2 and "its img/ and interim/ folders" in capsys.readouterr().err
    assert extract.read_bytes() == b"the real EAGLE-I extract"


def test_a_folder_that_may_not_be_entered_is_compared_by_name_only(tmp_path, monkeypatch, capsys):
    """data/raw as a link into a folder this user may not enter (someone else's disk): where it lies cannot be looked
    up. That is no reason to stop a run whose scratch folder is somewhere else; nor is a scratch folder that cannot be
    looked up (no rebuild can write there). The link's own name and the name of its target are refused all the same."""
    repo, locked = tmp_path / "repo", tmp_path / "locked"
    (repo / "docs").mkdir(parents=True)
    (repo / "data").mkdir()
    (locked / "raw").mkdir(parents=True)
    (repo / "data" / "raw").symlink_to(locked / "raw", target_is_directory=True)
    monkeypatch.setattr(reproduce, "REPO", repo)
    locked.chmod(0)
    try:
        assert not refused(tmp_path / "scratch", capsys) and not refused(locked / "elsewhere", capsys)
        assert refused(repo / "data" / "raw", capsys) and refused(locked / "raw", capsys)
    finally:
        locked.chmod(0o755)  # so that pytest can clear its folder away


def test_the_folders_looked_up_through_links_are_the_ones_the_pipeline_keeps_its_files_in():
    pipeline = (table_mod.RAW, table_mod.INTERIM, table_mod.PROCESSED, table_mod.IMG)
    kept = {folder.relative_to(table_mod.REPO).as_posix() for folder in pipeline}
    kept.add(reproduce.SAMPLE.parent.relative_to(reproduce.REPO).as_posix())
    assert kept == {"data/raw", "data/interim", "data/processed", "docs/img", "data/sample"}
    assert set(reproduce.PROTECTED_INSIDE) >= kept
    assert all(part.split("/")[0] in reproduce.PROTECTED for part in reproduce.PROTECTED_INSIDE)  # all inside them


def test_run_level_keeps_a_given_scratch_folder_and_removes_its_own(tmp_path, monkeypatch):
    used = []
    monkeypatch.setattr(reproduce, "level1", lambda report, scratch: used.append((scratch, scratch.is_dir())))
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    given = tmp_path / "given"
    given.mkdir()
    reproduce.run_level(report, reproduce.parse_args(["--level", "1", "--scratch", str(given)]))
    reproduce.run_level(report, reproduce.parse_args(["--level", "1"]))
    assert used[0] == (given, True) and given.is_dir()
    assert used[1][1] and not used[1][0].exists()  # the temp folder was there for the build and is gone afterwards


# --- rebuild(), level 1 and level 2, with the build itself replaced -----------------------------------------------

@pytest.fixture
def stub_build(monkeypatch) -> dict:
    """rebuild() with build_storm replaced: the stub notes what it was asked for, writes the summary a real build
    writes (listing the `problems` a test puts into the returned dict) and hands back the committed sample."""
    asked = {"problems": []}

    def build_storm(storm, *, counties, processed, img, interim):
        asked.update(fips=sorted(counties["fips"]), processed=processed, img=img, interim=interim,
                     stale_extract=table_mod.eaglei_extract_path(storm, interim).exists())
        processed.mkdir(parents=True, exist_ok=True)
        (processed / f"county_nights_{storm.id}.json").write_text(json.dumps(
            {"storm": storm.id, "tiles": ["h09v06"], "nights": 55, "problems": asked["problems"]}))
        return SAMPLE.copy()

    monkeypatch.setattr(table_mod, "build_storm", build_storm)
    monkeypatch.setattr(blackout.counties, "load_counties",
                        lambda states: pd.DataFrame({"fips": [*reproduce.SAMPLE_COUNTIES, "12086"]}))
    return asked


def test_level_1_rebuilds_the_sample_counties_into_scratch_and_compares_them(tmp_path, stub_build):
    stale = tmp_path / "interim" / "eaglei_ian2022.parquet"
    stale.parent.mkdir()
    stale.write_bytes(b"left behind by a run that was killed")
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    reproduce.level1(report, tmp_path)
    assert [(check.name, check.passed) for check in report.checks] == [
        ("satellite downloads", True), ("Ian: three sample counties rebuilt from NASA and EAGLE-I", True)]
    assert "165 county-nights match" in report.checks[1].detail and report.build["tiles"] == ["h09v06"]
    assert stub_build["fips"] == sorted(reproduce.SAMPLE_COUNTIES) and not stub_build["stale_extract"]
    assert (stub_build["processed"], stub_build["img"], stub_build["interim"]) == (
        tmp_path, tmp_path / "img", tmp_path / "interim") == reproduce.scratch_folders(tmp_path)  # the guard's folders


def test_level_2_compares_every_county_with_the_committed_fingerprint(tmp_path, monkeypatch, stub_build):
    committed = tmp_path / "fingerprint.json"
    committed.write_text(json.dumps(FP))
    monkeypatch.setattr(reproduce, "FINGERPRINT", committed)
    report = reproduce.Report(2, "2026-01-01T00:00:00+00:00", "local")
    reproduce.level2(report, tmp_path / "scratch")
    assert [check.passed for check in report.checks] == [True, True]
    assert "Lee County's series match" in report.checks[1].detail
    assert stub_build["fips"] == sorted([*reproduce.SAMPLE_COUNTIES, "12086"])  # no county is left out


@pytest.mark.parametrize("level", ["level1", "level2"])
def test_a_failed_download_fails_the_run_and_the_comparison_is_skipped(tmp_path, monkeypatch, stub_build, level):
    stub_build["problems"] = ["A2 2022-09-29: OSError: 503 for 'https://d1.cloudfront.net/x.h5?Signature=SECRET'",
                              "A1 2022-09-30: not in the archive"]
    for comparison in ("compare_tables", "compare_fingerprints"):
        monkeypatch.setattr(reproduce, comparison, lambda *args: pytest.fail("the tables must not be compared"))
    report = reproduce.Report(1, "2026-01-01T00:00:00+00:00", "local")
    getattr(reproduce, level)(report, tmp_path)
    downloads, comparison = report.checks
    assert not downloads.passed and "2 satellite files could not be read" in downloads.detail
    assert not comparison.passed and comparison.detail.startswith("not compared: 2 satellite files were not read")
    kept = (tmp_path / "county_nights_ian2022.json").read_text()  # the summary a kept scratch folder holds
    assert "SECRET" not in kept + json.dumps(report.payload()) and "x.h5?<redacted>" in kept


# --- docs/reproduce/plan.md: what the plan says of the suite and of the fingerprint -----------------------------

def plan() -> str:
    return (REPO / "docs/reproduce/plan.md").read_text(encoding="utf-8")


def test_the_plan_says_that_the_fingerprint_counts_the_values_present():
    """Level 2 is described by what its fingerprint holds; the counts of present values are part of that."""
    (level_2,) = [line for line in plan().splitlines() if line.startswith("- **Level 2 pass:**")]
    assert all(f"`{key}`" in level_2 for key in NEW_KEYS) and "a missing value from a zero" in level_2


@pytest.mark.parametrize("target", ["docs/lockbox_result.json", "data/processed/report.json", "docs/reproduce/out.json"])
def test_a_report_inside_data_or_docs_is_refused(target, capsys):
    with pytest.raises(SystemExit) as stop:
        reproduce.parse_args(["--level", "0", "--report", str(REPO / target)])
    assert stop.value.code == 2 and "--report must be outside data/ and docs/" in capsys.readouterr().err


def test_a_report_elsewhere_is_accepted(tmp_path):
    args = reproduce.parse_args(["--level", "0", "--report", str(tmp_path / "report.json")])
    assert args.report == tmp_path / "report.json"


def test_a_relative_report_is_judged_from_the_current_folder(monkeypatch):
    monkeypatch.chdir(REPO)  # what the GitHub workflow does: --report reproduce-report.json in the checkout
    args = reproduce.parse_args(["--level", "0", "--report", "reproduce-report.json"])
    assert args.report == Path("reproduce-report.json")
    monkeypatch.chdir(REPO / "docs")
    with pytest.raises(SystemExit):
        reproduce.parse_args(["--level", "0", "--report", "report.json"])
