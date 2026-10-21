"""End-to-end tests for the AsteroidBelt command-line tool.

Every test drives the real CLI in a subprocess against a throwaway data file,
so what is asserted here is exactly what a user (or a transcript) sees.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "asteroidbelt.py"

sys.path.insert(0, str(ROOT))
import asteroidbelt  # noqa: E402  (import after the path fix)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@pytest.fixture()
def data_file(tmp_path: Path) -> Path:
    return tmp_path / "data.json"


def run(*args: object, data: Optional[Path] = None, env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT)]
    if data is not None:
        command += ["--data", str(data)]
    command += [str(argument) for argument in args]
    environment = {key: value for key, value in os.environ.items()
                   if key != "ASTEROIDBELT_DATA"}
    if env:
        environment.update(env)
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          env=environment, cwd=str(cwd or ROOT), timeout=60)


def configured(data: Path) -> None:
    result = run("config", "set", "--focal-length", "1200", "--aperture", "200", data=data)
    assert result.returncode == 0, result.stderr


def write_state(path: Path, state: Dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_state(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def catalog_rows(text: str) -> List[str]:
    """Only the data rows of a targets table (the header also starts with "M")."""
    return [line for line in text.splitlines() if re.match(r"^M\d+\s", line)]


def base_state(observed: Optional[List[int]] = None) -> Dict[str, Any]:
    observations = [
        {"id": index, "session_id": 1, "messier": "M{}".format(number),
         "observed_at": "2025-01-10T22:00:00", "note": None}
        for index, number in enumerate(observed or [], start=1)
    ]
    return {
        "schema_version": 1,
        "config": {"focal_length_mm": 1200, "aperture_mm": 200},
        "eyepieces": [],
        "sessions": [{"id": 1, "date": "2025-01-10", "title": "Cold night",
                      "created_at": "2025-01-10T21:00:00"}],
        "observations": observations,
    }


# --------------------------------------------------------------------------- #
# T1 — CLI skeleton and atomic JSON store
# --------------------------------------------------------------------------- #


def test_config_show_creates_the_data_file(data_file: Path) -> None:
    result = run("config", "show", data=data_file)
    assert result.returncode == 0
    assert "focal length: (unset)" in result.stdout
    assert "aperture: (unset)" in result.stdout
    assert "data file: " in result.stdout
    assert data_file.exists()
    state = read_state(data_file)
    assert state["schema_version"] == 1
    assert state["config"] == {"focal_length_mm": None, "aperture_mm": None}
    assert state["eyepieces"] == [] and state["sessions"] == []
    assert result.stderr == ""


def test_env_var_selects_the_data_file(tmp_path: Path) -> None:
    target = tmp_path / "env.json"
    environment = {"ASTEROIDBELT_DATA": str(target)}
    added = run("eyepieces", "add", "--name", "25mm Plössl",
                "--focal-length", "25", "--afov", "52", env=environment)
    assert added.returncode == 0, added.stderr
    listed = run("eyepieces", "list", env=environment)
    assert listed.returncode == 0
    assert "25mm Plössl" in listed.stdout
    assert target.exists()


def test_corrupt_data_file_exits_1_with_one_error_line(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    for arguments in (("config", "show"), ("targets",), ("session", "list")):
        result = run(*arguments, data=broken)
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.startswith("error: ")
        assert result.stderr.count("\n") == 1
        assert "broken.json" in result.stderr
        assert "Traceback" not in result.stderr


def test_data_file_is_indented_json_written_atomically(data_file: Path, tmp_path: Path) -> None:
    configured(data_file)
    text = data_file.read_text(encoding="utf-8")
    assert text.startswith("{\n  \"schema_version\"")
    assert '"focal_length_mm": 1200' in text
    leftovers = [item.name for item in tmp_path.iterdir() if item.name.startswith(".asteroidbelt-")]
    assert leftovers == []


def test_bare_invocation_prints_usage_and_exits_0() -> None:
    result = run()
    assert result.returncode == 0
    assert "usage: asteroidbelt" in result.stdout
    assert "--version" in result.stdout


def test_version_flag() -> None:
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "asteroidbelt {}".format(asteroidbelt.__version__)


# --------------------------------------------------------------------------- #
# T2 — catalog, month-range renderer, season key
# --------------------------------------------------------------------------- #


def test_catalog_holds_110_ordered_objects() -> None:
    catalog = asteroidbelt.MESSIER_CATALOG
    assert len(catalog) == 110
    assert [target["number"] for target in catalog] == list(range(1, 111))
    for target in catalog:
        assert target["best_months"], target["messier"]
        assert target["season_key"] == target["best_months"][0]


@pytest.mark.parametrize("months, expected", [
    ([11, 12, 1], "Nov–Jan"),
    ([3, 4, 5, 9], "Mar–May, Sep"),
    (list(range(1, 13)), "All year"),
    ([2], "Feb"),
    ([1, 7], "Jan, Jul"),
    ([5, 6, 7, 11, 12], "May–Jul, Nov–Dec"),
    ([12, 11, 12, 1, 1], "Nov–Jan"),
])
def test_render_month_range(months: List[int], expected: str) -> None:
    assert asteroidbelt.render_month_range(months) == expected


def test_m31_window_and_season_marker(data_file: Path) -> None:
    result = run("targets", "--search", "m31", data=data_file)
    assert result.returncode == 0
    rows = [line for line in result.stdout.splitlines() if line.startswith("M31")]
    assert len(rows) == 1
    row = rows[0]
    assert "Andromeda Galaxy" in row
    assert "galaxy" in row
    assert "And" in row
    assert "3.4" in row
    assert "Aug–Feb" in row


def test_season_marker_marks_only_in_season_objects(data_file: Path) -> None:
    result = run("targets", "--month", "4", data=data_file)
    assert result.returncode == 0
    rows = catalog_rows(result.stdout)
    assert rows, result.stdout
    assert all(line.rstrip().endswith("yes") for line in rows)
    everybody = run("targets", data=data_file).stdout.splitlines()
    marked = [line for line in everybody if line.rstrip().endswith("yes")]
    assert marked == []  # today is only one month; never all 110 are in season
    unchecked = [line for line in catalog_rows("\n".join(everybody))
                 if line.rstrip().endswith("-")]
    assert unchecked


# --------------------------------------------------------------------------- #
# T3 — telescope config
# --------------------------------------------------------------------------- #


def test_config_set_persists_and_unsets(data_file: Path) -> None:
    configured(data_file)
    shown = run("config", "show", data=data_file)
    assert "focal length: 1200 mm" in shown.stdout
    assert "aperture: 200 mm" in shown.stdout

    unset = run("config", "set", "--focal-length", "none", data=data_file)
    assert unset.returncode == 0
    shown = run("config", "show", data=data_file)
    assert "focal length: (unset)" in shown.stdout
    assert "aperture: 200 mm" in shown.stdout


@pytest.mark.parametrize("bad", ["0", "-40", "abc", "12.5"])
def test_config_set_rejects_bad_values_and_keeps_state(data_file: Path, bad: str) -> None:
    configured(data_file)
    result = run("config", "set", "--focal-length", bad, data=data_file)
    assert result.returncode == 2
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error: ")
    assert "positive whole number" in lines[0]
    assert '"{}"'.format(bad) in lines[0]
    assert read_state(data_file)["config"]["focal_length_mm"] == 1200


def test_config_set_requires_at_least_one_value(data_file: Path) -> None:
    result = run("config", "set", data=data_file)
    assert result.returncode == 2
    assert result.stderr.startswith("error: give at least one of --focal-length or --aperture")


# --------------------------------------------------------------------------- #
# T4 — eyepieces and derived optics
# --------------------------------------------------------------------------- #


def test_eyepiece_row_shows_derived_optics(data_file: Path) -> None:
    configured(data_file)
    added = run("eyepieces", "add", "--name", "25mm Plössl",
                "--focal-length", "25", "--afov", "52", data=data_file)
    assert added.returncode == 0
    assert 'added eyepiece #1: 25mm Plössl (48x)' in added.stdout
    listed = run("eyepieces", "list", data=data_file)
    assert listed.returncode == 0
    assert listed.stderr == ""
    row = [line for line in listed.stdout.splitlines() if "25mm Plössl" in line][0]
    assert "48x" in row
    assert "4.2" in row
    assert "1.08°" in row


def test_eyepieces_sorted_by_magnification_descending(data_file: Path) -> None:
    configured(data_file)
    for name, focal, afov in (("32mm Plössl", 32, 50), ("9mm Ortho", 9, 42),
                              ("18mm Radian", 18, 60)):
        assert run("eyepieces", "add", "--name", name, "--focal-length", focal,
                   "--afov", afov, data=data_file).returncode == 0
    rows = [line for line in run("eyepieces", "list", data=data_file).stdout.splitlines()
            if "mm " in line or "Ortho" in line or "Radian" in line or "Plössl" in line]
    assert [row.split()[1] for row in rows] == ["9mm", "18mm", "32mm"]


def test_degraded_mode_without_focal_length(data_file: Path) -> None:
    run("config", "set", "--aperture", "200", data=data_file)
    run("eyepieces", "add", "--name", "25mm Plössl", "--focal-length", "25",
        "--afov", "52", data=data_file)
    run("eyepieces", "add", "--name", "9mm Ortho", "--focal-length", "9",
        "--afov", "42", data=data_file)
    result = run("eyepieces", "list", data=data_file)
    assert result.returncode == 0
    warnings = result.stderr.strip().splitlines()
    assert len(warnings) == 1
    assert warnings[0].startswith("warning: ")
    assert "focal length is not set" in warnings[0]
    rows = [line for line in result.stdout.splitlines() if "mm " in line or "Ortho" in line
            or "Plössl" in line]
    assert len(rows) == 2
    assert all("—" in row for row in rows)
    assert rows[0].split()[1] == "9mm"  # focal length ascending


def test_degraded_mode_without_aperture(data_file: Path) -> None:
    run("config", "set", "--focal-length", "1200", data=data_file)
    run("eyepieces", "add", "--name", "25mm Plössl", "--focal-length", "25",
        "--afov", "52", data=data_file)
    result = run("eyepieces", "list", data=data_file)
    assert result.returncode == 0
    warnings = result.stderr.strip().splitlines()
    assert len(warnings) == 1 and "aperture is not set" in warnings[0]
    row = [line for line in result.stdout.splitlines() if "25mm Plössl" in line][0]
    assert "48x" in row
    assert "1.08°" in row
    assert "—" in row


def test_eyepiece_validation_and_removal(data_file: Path) -> None:
    configured(data_file)
    run("eyepieces", "add", "--name", "25mm Plössl", "--focal-length", "25",
        "--afov", "52", data=data_file)

    duplicate = run("eyepieces", "add", "--name", "25mm Plössl", "--focal-length", "25",
                    "--afov", "52", data=data_file)
    assert duplicate.returncode == 2
    assert duplicate.stderr.startswith("error: ")
    assert "already exists" in duplicate.stderr
    assert len(read_state(data_file)["eyepieces"]) == 1

    unknown = run("eyepieces", "remove", "99", data=data_file)
    assert unknown.returncode == 2
    assert "no eyepiece #99" in unknown.stderr
    assert len(read_state(data_file)["eyepieces"]) == 1

    removed = run("eyepieces", "remove", "1", data=data_file)
    assert removed.returncode == 0
    assert "removed eyepiece #1" in removed.stdout
    assert read_state(data_file)["eyepieces"] == []


def test_eyepieces_empty_state(data_file: Path) -> None:
    result = run("eyepieces", "list", data=data_file)
    assert result.returncode == 0
    assert 'no eyepieces yet — add one with: asteroidbelt eyepieces add --name "25mm Plössl"' \
        in result.stdout


# --------------------------------------------------------------------------- #
# T5 — the targets table and its filters
# --------------------------------------------------------------------------- #


def test_targets_table_is_80_columns_and_counted(data_file: Path) -> None:
    result = run("targets", data=data_file)
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert len(lines) == 110 + 2 + 1  # header, rule, rows, count
    assert all(len(line) <= 80 for line in lines), max(len(line) for line in lines)
    assert lines[-1] == "110 of 110 targets"
    numbers = [int(line.split()[0][1:]) for line in lines[2:-1]]
    keys = [(asteroidbelt.CATALOG_BY_NUMBER[number]["season_key"], number)
            for number in numbers]
    assert keys == sorted(keys)


def test_targets_filters(data_file: Path) -> None:
    january = run("targets", "--month", "1", data=data_file)
    january_rows = catalog_rows(january.stdout)
    january_numbers = {int(row.split()[0][1:]) for row in january_rows}
    assert january_numbers
    for number in january_numbers:
        assert 1 in asteroidbelt.CATALOG_BY_NUMBER[number]["best_months"]
    assert january.stdout.strip().splitlines()[-1].endswith("of 110 targets")

    andromeda = run("targets", "--type", "galaxy", "--constellation", "And", data=data_file)
    andromeda_rows = catalog_rows(andromeda.stdout)
    assert andromeda_rows
    for row in andromeda_rows:
        assert "galaxy" in row and "And" in row

    orion = run("targets", "--search", "orion", data=data_file)
    assert "Orion Nebula" in orion.stdout
    assert "1 of 110 targets" in orion.stdout


def test_targets_empty_state_names_the_filters(data_file: Path) -> None:
    result = run("targets", "--search", "zzz", data=data_file)
    assert result.returncode == 0
    assert result.stdout.strip() == \
        "no targets match --search zzz — widen or clear the filters"


def test_targets_rejects_bad_month(data_file: Path) -> None:
    for bad in ("13", "0", "abc"):
        result = run("targets", "--month", bad, data=data_file)
        assert result.returncode == 2
        assert result.stderr.startswith("error: --month")
        assert result.stderr.count("\n") == 1


# --------------------------------------------------------------------------- #
# T6 / T7 — the session lifecycle
# --------------------------------------------------------------------------- #


def test_session_start_prints_id_and_hint(data_file: Path) -> None:
    result = run("session", "start", "--date", "2025-01-10", "--title", "Cold night",
                 data=data_file)
    assert result.returncode == 0
    assert 'started session 1 — 2025-01-10 "Cold night"' in result.stdout
    assert "asteroidbelt session mark 1 M31" in result.stdout
    assert read_state(data_file)["sessions"][0]["date"] == "2025-01-10"


def test_session_mark_show_and_unmark(data_file: Path) -> None:
    run("session", "start", "--date", "2025-01-10", "--title", "Cold night", data=data_file)
    marked = run("session", "mark", "1", "M42", "--note", "Trapezium split at 48x",
                 data=data_file)
    assert marked.returncode == 0
    assert "marked M42 in session 1 (1 of 110 observed)" in marked.stdout

    shown = run("session", "show", "1", data=data_file)
    assert shown.returncode == 0
    assert "observed 1 / remaining 109" in shown.stdout
    assert "  M42  Orion Nebula" in shown.stdout
    assert "    Trapezium split at 48x" in shown.stdout
    assert "Remaining" in shown.stdout
    assert "M42" not in shown.stdout.split("Remaining", 1)[1]

    unmarked = run("session", "unmark", "1", "M42", data=data_file)
    assert unmarked.returncode == 0
    assert "unmarked M42 in session 1 (0 of 110 observed)" in unmarked.stdout
    assert read_state(data_file)["observations"] == []
    shown_again = run("session", "show", "1", data=data_file)
    assert "observed 0 / remaining 110" in shown_again.stdout
    assert "asteroidbelt session mark 1 M31" in shown_again.stdout
    assert "Trapezium" not in shown_again.stdout


def test_session_mark_rejections_leave_state_untouched(data_file: Path) -> None:
    run("session", "start", "--date", "2025-01-10", "--title", "Cold night", data=data_file)
    run("session", "mark", "1", "M42", data=data_file)
    before = read_state(data_file)

    duplicate = run("session", "mark", "1", "M42", data=data_file)
    assert duplicate.returncode == 2 and "already marked" in duplicate.stderr

    unknown_object = run("session", "mark", "1", "M999", data=data_file)
    assert unknown_object.returncode == 2 and "M999" in unknown_object.stderr

    unknown_session = run("session", "mark", "99", "M31", data=data_file)
    assert unknown_session.returncode == 2 and "no session 99" in unknown_session.stderr

    long_note = run("session", "mark", "1", "M31", "--note", "x" * 201, data=data_file)
    assert long_note.returncode == 2 and "200" in long_note.stderr

    for failure in (duplicate, unknown_object, unknown_session, long_note):
        assert failure.stdout == ""
        assert failure.stderr.count("\n") == 1
        assert "Traceback" not in failure.stderr
    assert read_state(data_file) == before


def test_session_show_wraps_and_orders_remaining(data_file: Path) -> None:
    run("session", "start", "--date", "2025-01-10", "--title", "Cold night", data=data_file)
    note = ("Clear night, transparency steady, Andromeda obvious naked eye, "
            "the Trapezium split cleanly at 48x and the Ring Nebula showed a soft oval.")
    run("session", "mark", "1", "M13", "--note", note, data=data_file)
    shown = run("session", "show", "1", data=data_file)
    lines = shown.stdout.splitlines()
    note_lines = [line for line in lines if line.startswith("    ")]
    assert len(note_lines) > 1
    assert all(len(line) <= 4 + asteroidbelt.NOTE_WIDTH for line in note_lines)
    assert " ".join(line.strip() for line in note_lines) == note

    remaining = lines[lines.index("Remaining") + 1:]
    numbers = [int(line.split()[0][1:]) for line in remaining]
    keys = [(asteroidbelt.CATALOG_BY_NUMBER[number]["season_key"], number)
            for number in numbers]
    assert keys == sorted(keys)
    assert 13 not in numbers


def test_session_show_rejects_unknown_session(data_file: Path) -> None:
    result = run("session", "show", "99", data=data_file)
    assert result.returncode == 2
    assert "no session 99 exists" in result.stderr


def test_session_show_states_everything_observed(tmp_path: Path) -> None:
    path = tmp_path / "complete.json"
    write_state(path, base_state(observed=list(range(1, 111))))
    result = run("session", "show", "1", data=path)
    assert result.returncode == 0
    assert "observed 110 / remaining 0" in result.stdout
    assert "all 110 Messier objects observed — nothing left" in result.stdout


def test_session_start_rejects_bad_date_and_title(data_file: Path) -> None:
    bad_date = run("session", "start", "--date", "10/01/2025", "--title", "Cold night",
                   data=data_file)
    assert bad_date.returncode == 2
    assert "YYYY-MM-DD" in bad_date.stderr
    missing_title = run("session", "start", data=data_file)
    assert missing_title.returncode == 2
    assert "--title is required" in missing_title.stderr
    # a validation failure must not create or touch the session list
    assert not data_file.exists() or read_state(data_file)["sessions"] == []


# --------------------------------------------------------------------------- #
# T8 — lifetime unobserved list
# --------------------------------------------------------------------------- #


def test_unobserved_uses_the_union_of_all_sessions(tmp_path: Path) -> None:
    path = tmp_path / "lifetime.json"
    state = base_state(observed=[42])
    state["sessions"].append({"id": 2, "date": "2025-02-02", "title": "Second night",
                              "created_at": "2025-02-02T21:00:00"})
    state["observations"].append({"id": 2, "session_id": 2, "messier": "M31",
                                  "observed_at": "2025-02-02T22:00:00", "note": None})
    write_state(path, state)

    result = run("targets", "--unobserved", data=path)
    assert result.returncode == 0
    rows = catalog_rows(result.stdout)
    assert len(rows) == 108
    numbers = {int(row.split()[0][1:]) for row in rows}
    assert 31 not in numbers and 42 not in numbers
    assert result.stdout.strip().splitlines()[-1] == "108 of 110 unobserved across 2 sessions"
    assert all(len(line) <= 80 for line in result.stdout.splitlines())

    april = run("targets", "--unobserved", "--month", "4", data=path)
    assert april.returncode == 0
    april_rows = catalog_rows(april.stdout)
    assert april_rows
    for row in april_rows:
        number = int(row.split()[0][1:])
        assert 4 in asteroidbelt.CATALOG_BY_NUMBER[number]["best_months"]


def test_unobserved_empty_state(tmp_path: Path) -> None:
    path = tmp_path / "complete.json"
    write_state(path, base_state(observed=list(range(1, 111))))
    result = run("targets", "--unobserved", data=path)
    assert result.returncode == 0
    assert result.stdout.strip() == "all 110 Messier objects have been observed"


# --------------------------------------------------------------------------- #
# T9 — session history
# --------------------------------------------------------------------------- #


def test_session_list_orders_by_date_then_id(data_file: Path) -> None:
    run("session", "start", "--date", "2025-03-01", "--title", "March", data=data_file)
    run("session", "start", "--date", "2025-01-10", "--title", "Cold night", data=data_file)
    run("session", "start", "--date", "2025-02-02", "--title", "February", data=data_file)
    for messier in ("M42", "M31", "M13"):
        run("session", "mark", "2", messier, data=data_file)

    result = run("session", "list", data=data_file)
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    rows = lines[2:-1]  # header, rule, three session rows, totals line
    assert [row.split()[1] for row in rows] == ["2025-01-10", "2025-02-02", "2025-03-01"]
    assert rows[0].split()[2:] == ["Cold", "night", "3", "107"]
    assert result.stdout.strip().splitlines()[-1] == \
        "3 sessions — 3 of 110 Messier objects observed"


def test_session_list_empty_state(data_file: Path) -> None:
    result = run("session", "list", data=data_file)
    assert result.returncode == 0
    assert result.stdout.strip() == \
        "no sessions yet — start one with: asteroidbelt session start"


# --------------------------------------------------------------------------- #
# Every successful command is quiet on stderr, every failure is one line
# --------------------------------------------------------------------------- #


def test_successful_commands_do_not_write_to_stderr(data_file: Path) -> None:
    commands = [
        ("config", "set", "--focal-length", "1200", "--aperture", "200"),
        ("eyepieces", "add", "--name", "25mm Plössl", "--focal-length", "25", "--afov", "52"),
        ("eyepieces", "list"),
        ("targets", "--type", "nebula"),
        ("session", "start", "--date", "2025-01-10", "--title", "Cold night"),
        ("session", "mark", "1", "M42"),
        ("session", "show", "1"),
        ("session", "list"),
        ("targets", "--unobserved"),
    ]
    for command in commands:
        result = run(*command, data=data_file)
        assert result.returncode == 0, (command, result.stderr)
        assert result.stderr == "", (command, result.stderr)


def test_usage_errors_are_single_lines_with_exit_2(data_file: Path) -> None:
    configured(data_file)
    failures = [
        ("eyepieces", "remove", "42"),
        ("session", "show", "7"),
        ("session", "mark", "1", "M999"),
        ("targets", "--month", "13"),
        ("config", "set", "--aperture", "none", "--focal-length", "-1"),
    ]
    for command in failures:
        result = run(*command, data=data_file)
        assert result.returncode == 2, command
        assert result.stdout == "", command
        lines = result.stderr.splitlines()
        assert len(lines) == 1 and lines[0].startswith("error: "), command
        assert "Traceback" not in result.stderr, command


# --------------------------------------------------------------------------- #
# The data file is a contract: bad rows are rejected, never rendered
# --------------------------------------------------------------------------- #


def test_data_file_with_unknown_observation_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    write_state(path, base_state(observed=[999]))
    result = run("session", "show", "1", data=path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ") and result.stderr.count("\n") == 1
    assert "M999" in result.stderr
    assert "Traceback" not in result.stderr


def test_data_file_with_dangling_session_reference_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    state = base_state(observed=[42])
    state["observations"][0]["session_id"] = 7
    write_state(path, state)
    result = run("targets", "--unobserved", data=path)
    assert result.returncode == 1
    assert "does not exist" in result.stderr


# --------------------------------------------------------------------------- #
# The committed transcript stays honest
# --------------------------------------------------------------------------- #


def test_demo_transcript_is_committed_and_host_path_free() -> None:
    transcript = (ROOT / "docs" / "demo.txt").read_text(encoding="utf-8")
    assert "$ asteroidbelt config set --focal-length 1200 --aperture 200" in transcript
    assert "added eyepiece #1" in transcript
    assert "marked M42 in session 1" in transcript
    assert "session list" in transcript
    for marker in ("/work", "/home/", "/root", "/tmp/", "C:\\"):
        assert marker not in transcript, marker
