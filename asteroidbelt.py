#!/usr/bin/env python3
"""AsteroidBelt — eyepiece magnifications, Messier viewing windows, session mark-offs.

A single-user, local, standard-library-only observing log.  Every command reads
and writes one indented JSON document chosen by ``--data`` or
``ASTEROIDBELT_DATA`` (default ``~/.asteroidbelt/data.json``).

Design notes that are not obvious from the code below:

* The Messier catalog is embedded in this file on purpose (D3): a user's data
  file never needs migrating when a catalog entry is corrected, and the
  lifetime "unobserved" list can always be measured against all 110 objects.
* Derived optics (magnification, exit pupil, TFOV) are computed on every read
  (D4).  Nothing derived is ever stored, so editing the telescope config
  instantly re-renders every eyepiece row.
* A missing telescope value is a *warning*, never an error (D5): the observer
  can add and browse eyepieces before they have measured their telescope.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
import textwrap
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "1.0.0"

PROGRAM = "asteroidbelt"
SCHEMA_VERSION = 1
CATALOG_SIZE = 110

EXIT_OK = 0
EXIT_DATA = 1
EXIT_USAGE = 2

COLUMN_WIDTH = 80
NOTE_WIDTH = 72
NOTE_MAX_CHARS = 200
NAME_MAX_CHARS = 60
TITLE_MAX_CHARS = 60

DEFAULT_DATA_PATH = "~/.asteroidbelt/data.json"
ENV_DATA_PATH = "ASTEROIDBELT_DATA"

DASH = "—"
MONTH_RANGE_SEPARATOR = "–"
MONTH_JOINER = ", "

MONTH_ABBR: Tuple[str, ...] = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


# --------------------------------------------------------------------------- #
# Errors and exit codes (D9: one helper, one line, one code per failure class)
# --------------------------------------------------------------------------- #


class AsteroidBeltError(Exception):
    """Base class for every expected failure; carries its own exit code."""

    exit_code = EXIT_USAGE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(AsteroidBeltError):
    """Bad flag value, unknown id, unknown object, duplicate mark: exit 2."""

    exit_code = EXIT_USAGE


class DataFileError(AsteroidBeltError):
    """The data file could not be read, parsed or written: exit 1."""

    exit_code = EXIT_DATA


# --------------------------------------------------------------------------- #
# Embedded Messier catalog (D3)
# --------------------------------------------------------------------------- #

# (number, common name, type, constellation, magnitude, first best month, month count)
# The best-month window is a contiguous run that may wrap the new year; it is
# authored in seasonal order, so the first month is also the object's sort key
# (D7).  Objects without a widely used common name carry their NGC/IC
# designation, which is what printed observing lists do.
_CATALOG_ROWS: Tuple[Tuple[int, str, str, str, float, int, int], ...] = (
    (1, "Crab Nebula", "supernova remnant", "Taurus", 8.4, 11, 4),
    (2, "NGC 7089", "globular cluster", "Aquarius", 6.5, 7, 5),
    (3, "NGC 5272", "globular cluster", "Canes Venatici", 6.2, 3, 5),
    (4, "NGC 6121", "globular cluster", "Scorpius", 5.9, 5, 4),
    (5, "NGC 5904", "globular cluster", "Serpens", 6.7, 4, 5),
    (6, "Butterfly Cluster", "open cluster", "Scorpius", 4.2, 5, 4),
    (7, "Ptolemy Cluster", "open cluster", "Scorpius", 3.3, 5, 4),
    (8, "Lagoon Nebula", "nebula", "Sagittarius", 6.0, 6, 4),
    (9, "NGC 6333", "globular cluster", "Ophiuchus", 7.7, 5, 4),
    (10, "NGC 6254", "globular cluster", "Ophiuchus", 6.6, 5, 4),
    (11, "Wild Duck Cluster", "open cluster", "Scutum", 6.3, 6, 4),
    (12, "NGC 6218", "globular cluster", "Ophiuchus", 6.7, 5, 4),
    (13, "Hercules Cluster", "globular cluster", "Hercules", 5.8, 4, 5),
    (14, "NGC 6402", "globular cluster", "Ophiuchus", 7.6, 5, 4),
    (15, "NGC 7078", "globular cluster", "Pegasus", 6.2, 7, 5),
    (16, "Eagle Nebula", "nebula", "Serpens", 6.0, 6, 4),
    (17, "Omega Nebula", "nebula", "Sagittarius", 6.0, 6, 4),
    (18, "NGC 6613", "open cluster", "Sagittarius", 7.5, 6, 4),
    (19, "NGC 6273", "globular cluster", "Ophiuchus", 6.8, 5, 4),
    (20, "Trifid Nebula", "nebula", "Sagittarius", 6.3, 6, 4),
    (21, "NGC 6531", "open cluster", "Sagittarius", 6.5, 6, 4),
    (22, "Sagittarius Cluster", "globular cluster", "Sagittarius", 5.1, 6, 4),
    (23, "NGC 6494", "open cluster", "Sagittarius", 6.9, 6, 4),
    (24, "Sagittarius Star Cloud", "asterism", "Sagittarius", 4.6, 6, 4),
    (25, "IC 4725", "open cluster", "Sagittarius", 6.5, 6, 4),
    (26, "NGC 6694", "open cluster", "Scutum", 8.0, 6, 4),
    (27, "Dumbbell Nebula", "planetary nebula", "Vulpecula", 7.5, 6, 5),
    (28, "NGC 6626", "globular cluster", "Sagittarius", 6.8, 6, 4),
    (29, "NGC 6913", "open cluster", "Cygnus", 7.1, 6, 5),
    (30, "NGC 7099", "globular cluster", "Capricornus", 7.2, 8, 4),
    (31, "Andromeda Galaxy", "galaxy", "Andromeda", 3.4, 8, 7),
    (32, "NGC 221", "galaxy", "Andromeda", 8.1, 8, 7),
    (33, "Triangulum Galaxy", "galaxy", "Triangulum", 5.7, 9, 5),
    (34, "NGC 1039", "open cluster", "Perseus", 5.5, 9, 5),
    (35, "NGC 2168", "open cluster", "[redacted]", 5.3, 11, 5),
    (36, "NGC 1960", "open cluster", "Auriga", 6.3, 11, 5),
    (37, "NGC 2099", "open cluster", "Auriga", 6.2, 11, 5),
    (38, "NGC 1912", "open cluster", "Auriga", 7.4, 11, 5),
    (39, "NGC 7092", "open cluster", "Cygnus", 5.5, 6, 5),
    (40, "Winnecke 4", "double star", "Ursa Major", 8.4, 3, 4),
    (41, "NGC 2287", "open cluster", "Canis Major", 4.5, 12, 4),
    (42, "Orion Nebula", "nebula", "Orion", 4.0, 12, 4),
    (43, "De Mairan's Nebula", "nebula", "Orion", 9.0, 12, 4),
    (44, "Beehive Cluster", "open cluster", "Cancer", 3.7, 1, 4),
    (45, "Pleiades", "open cluster", "Taurus", 1.6, 10, 5),
    (46, "NGC 2437", "open cluster", "Puppis", 6.1, 12, 4),
    (47, "NGC 2422", "open cluster", "Puppis", 4.4, 12, 4),
    (48, "NGC 2548", "open cluster", "Hydra", 5.8, 1, 4),
    (49, "NGC 4472", "galaxy", "Virgo", 8.4, 3, 5),
    (50, "NGC 2323", "open cluster", "Monoceros", 5.9, 12, 4),
    (51, "Whirlpool Galaxy", "galaxy", "Canes Venatici", 8.4, 3, 5),
    (52, "NGC 7654", "open cluster", "Cassiopeia", 6.9, 8, 5),
    (53, "NGC 5024", "globular cluster", "Coma Berenices", 7.6, 3, 5),
    (54, "NGC 6715", "globular cluster", "Sagittarius", 7.6, 6, 4),
    (55, "NGC 6809", "globular cluster", "Sagittarius", 6.3, 6, 4),
    (56, "NGC 6779", "globular cluster", "Lyra", 8.3, 5, 5),
    (57, "Ring Nebula", "planetary nebula", "Lyra", 8.8, 5, 5),
    (58, "NGC 4579", "galaxy", "Virgo", 9.7, 3, 5),
    (59, "NGC 4621", "galaxy", "Virgo", 9.6, 3, 5),
    (60, "NGC 4649", "galaxy", "Virgo", 8.8, 3, 5),
    (61, "NGC 4303", "galaxy", "Virgo", 9.7, 3, 5),
    (62, "NGC 6266", "globular cluster", "Ophiuchus", 6.5, 5, 4),
    (63, "Sunflower Galaxy", "galaxy", "Canes Venatici", 8.6, 3, 5),
    (64, "Black Eye Galaxy", "galaxy", "Coma Berenices", 8.5, 3, 5),
    (65, "NGC 3623", "galaxy", "Leo", 9.3, 3, 5),
    (66, "NGC 3627", "galaxy", "Leo", 8.9, 3, 5),
    (67, "NGC 2682", "open cluster", "Cancer", 6.1, 1, 4),
    (68, "NGC 4590", "globular cluster", "Hydra", 8.2, 3, 4),
    (69, "NGC 6637", "globular cluster", "Sagittarius", 7.6, 6, 4),
    (70, "NGC 6681", "globular cluster", "Sagittarius", 7.9, 6, 4),
    (71, "NGC 6838", "globular cluster", "Sagitta", 8.2, 6, 4),
    (72, "NGC 6981", "globular cluster", "Aquarius", 9.3, 7, 5),
    (73, "NGC 6994", "asterism", "Aquarius", 9.0, 7, 5),
    (74, "Phantom Galaxy", "galaxy", "Pisces", 9.4, 9, 5),
    (75, "NGC 6864", "globular cluster", "Sagittarius", 8.5, 6, 4),
    (76, "Little Dumbbell Nebula", "planetary nebula", "Perseus", 10.1, 9, 5),
    (77, "Cetus A", "galaxy", "Cetus", 8.9, 10, 4),
    (78, "NGC 2068", "nebula", "Orion", 8.3, 12, 4),
    (79, "NGC 1904", "globular cluster", "Lepus", 8.2, 12, 4),
    (80, "NGC 6093", "globular cluster", "Scorpius", 7.3, 5, 4),
    (81, "Bode's Galaxy", "galaxy", "Ursa Major", 6.9, 2, 5),
    (82, "Cigar Galaxy", "galaxy", "Ursa Major", 8.4, 2, 5),
    (83, "Southern Pinwheel", "galaxy", "Hydra", 7.5, 3, 5),
    (84, "NGC 4374", "galaxy", "Virgo", 9.1, 3, 5),
    (85, "NGC 4382", "galaxy", "Coma Berenices", 9.1, 3, 5),
    (86, "NGC 4406", "galaxy", "Virgo", 8.9, 3, 5),
    (87, "Virgo A", "galaxy", "Virgo", 8.6, 3, 5),
    (88, "NGC 4501", "galaxy", "Coma Berenices", 9.6, 3, 5),
    (89, "NGC 4552", "galaxy", "Virgo", 9.8, 3, 5),
    (90, "NGC 4569", "galaxy", "Virgo", 9.5, 3, 5),
    (91, "NGC 4548", "galaxy", "Coma Berenices", 10.2, 3, 5),
    (92, "NGC 6341", "globular cluster", "Hercules", 6.4, 4, 5),
    (93, "NGC 2447", "open cluster", "Puppis", 6.0, 12, 4),
    (94, "NGC 4736", "galaxy", "Canes Venatici", 8.2, 3, 5),
    (95, "NGC 3351", "galaxy", "Leo", 9.7, 3, 5),
    (96, "NGC 3368", "galaxy", "Leo", 9.2, 3, 5),
    (97, "Owl Nebula", "planetary nebula", "Ursa Major", 9.9, 2, 5),
    (98, "NGC 4192", "galaxy", "Coma Berenices", 10.1, 3, 5),
    (99, "Coma Pinwheel Galaxy", "galaxy", "Coma Berenices", 9.9, 3, 5),
    (100, "NGC 4321", "galaxy", "Coma Berenices", 9.3, 3, 5),
    (101, "Pinwheel Galaxy", "galaxy", "Ursa Major", 7.9, 3, 5),
    (102, "Spindle Galaxy", "galaxy", "Draco", 10.0, 4, 5),
    (103, "NGC 581", "open cluster", "Cassiopeia", 7.4, 8, 5),
    (104, "Sombrero Galaxy", "galaxy", "Virgo", 8.0, 3, 5),
    (105, "NGC 3379", "galaxy", "Leo", 9.3, 3, 5),
    (106, "NGC 4258", "galaxy", "Canes Venatici", 8.4, 3, 5),
    (107, "NGC 6171", "globular cluster", "Ophiuchus", 7.9, 5, 4),
    (108, "Surfboard Galaxy", "galaxy", "Ursa Major", 10.0, 2, 5),
    (109, "NGC 3992", "galaxy", "Ursa Major", 9.8, 2, 5),
    (110, "NGC 205", "galaxy", "Andromeda", 8.5, 8, 7),
)

#: IAU three-letter abbreviations, used in the table to keep it inside 80 columns.
CONSTELLATION_ABBR: Dict[str, str] = {
    "Andromeda": "And",
    "Aquarius": "Aqr",
    "Auriga": "Aur",
    "Cancer": "Cnc",
    "Canes Venatici": "CVn",
    "Canis Major": "CMa",
    "Capricornus": "Cap",
    "Cassiopeia": "Cas",
    "Cetus": "Cet",
    "Coma Berenices": "Com",
    "Cygnus": "Cyg",
    "Draco": "Dra",
    "[redacted]": "Gem",
    "Hercules": "Her",
    "Hydra": "Hya",
    "Leo": "Leo",
    "Lepus": "Lep",
    "Lyra": "Lyr",
    "Monoceros": "Mon",
    "Ophiuchus": "Oph",
    "Orion": "Ori",
    "Pegasus": "Peg",
    "Perseus": "Per",
    "Pisces": "Psc",
    "Puppis": "Pup",
    "Sagitta": "Sge",
    "Sagittarius": "Sgr",
    "Scorpius": "Sco",
    "Scutum": "Sct",
    "Serpens": "Ser",
    "Taurus": "Tau",
    "Triangulum": "Tri",
    "Ursa Major": "UMa",
    "Virgo": "Vir",
    "Vulpecula": "Vul",
}

#: Table labels for the object types; the full type names are used by --type.
TYPE_LABEL: Dict[str, str] = {
    "galaxy": "galaxy",
    "globular cluster": "globular cl.",
    "open cluster": "open cluster",
    "nebula": "nebula",
    "planetary nebula": "planetary neb.",
    "supernova remnant": "supernova rem.",
    "asterism": "asterism",
    "double star": "double star",
}


def _month_run(first_month: int, month_count: int) -> Tuple[int, ...]:
    """Expand a (first month, length) pair into a wrapping run of months."""
    return tuple(((first_month - 1 + offset) % 12) + 1 for offset in range(month_count))


#: The embedded catalog: an immutable tuple of dicts, never written to disk.
MESSIER_CATALOG: Tuple[Dict[str, Any], ...] = tuple(
    {
        "number": number,
        "messier": "M{}".format(number),
        "name": name,
        "type": obj_type,
        "constellation": constellation,
        "magnitude": magnitude,
        "best_months": _month_run(first_month, month_count),
        "season_key": first_month,
    }
    for number, name, obj_type, constellation, magnitude, first_month, month_count
    in _CATALOG_ROWS
)

CATALOG_BY_NUMBER: Dict[int, Dict[str, Any]] = {
    target["number"]: target for target in MESSIER_CATALOG
}


def _self_check_catalog() -> None:
    """Fail loudly at import time if the embedded catalog is inconsistent."""
    if len(MESSIER_CATALOG) != CATALOG_SIZE:
        raise AssertionError("catalog must hold {} objects, holds {}".format(
            CATALOG_SIZE, len(MESSIER_CATALOG)))
    numbers = [target["number"] for target in MESSIER_CATALOG]
    if numbers != list(range(1, CATALOG_SIZE + 1)):
        raise AssertionError("catalog Messier numbers must run M1..M110 in order")
    for target in MESSIER_CATALOG:
        months = target["best_months"]
        if not months or any(month < 1 or month > 12 for month in months):
            raise AssertionError("bad best_months for {}".format(target["messier"]))
        if target["season_key"] != months[0]:
            raise AssertionError("season_key must equal best_months[0]")
        if target["constellation"] not in CONSTELLATION_ABBR:
            raise AssertionError(
                "missing abbreviation for {}".format(target["constellation"]))
        if target["type"] not in TYPE_LABEL:
            raise AssertionError("missing type label for {}".format(target["type"]))
        if len(target["name"]) > 22:
            raise AssertionError(
                "name too wide for the 80-column table: {!r}".format(target["name"]))


_self_check_catalog()


# --------------------------------------------------------------------------- #
# Month-range rendering (D6) and ordering (D7)
# --------------------------------------------------------------------------- #


def render_month_range(months: Iterable[int]) -> str:
    """Render a set of months as collapsed runs, e.g. [3, 4, 5, 9] -> "Mar–May, Sep".

    The year is treated as a ring: the widest gap decides which run leads, so
    November/December/January renders as "Nov–Jan" instead of a naive
    "Jan, Nov–Dec".  Ties on gap width break towards the earliest starting
    month, which keeps the output stable for transcripts and diffs.
    """
    unique = sorted({int(month) for month in months})
    if not unique:
        return DASH
    if len(unique) == 1:
        return MONTH_ABBR[unique[0]]
    if len(unique) == 12:
        return "All year"

    gaps: List[Tuple[int, int]] = []
    for index, month in enumerate(unique):
        following = unique[(index + 1) % len(unique)]
        gaps.append(((following - month) % 12, following))
    # widest gap first, then the earliest starting month
    _, start_month = max(gaps, key=lambda gap: (gap[0], -gap[1]))
    offset = unique.index(start_month)
    ordered = unique[offset:] + unique[:offset]

    runs: List[List[int]] = [[ordered[0]]]
    for month in ordered[1:]:
        if (month - runs[-1][-1]) % 12 == 1:
            runs[-1].append(month)
        else:
            runs.append([month])

    rendered = []
    for run in runs:
        if len(run) == 1:
            rendered.append(MONTH_ABBR[run[0]])
        else:
            rendered.append("{}{}{}".format(
                MONTH_ABBR[run[0]], MONTH_RANGE_SEPARATOR, MONTH_ABBR[run[-1]]))
    return MONTH_JOINER.join(rendered)


def season_sort_key(target: Dict[str, Any]) -> Tuple[int, int]:
    """Every ordered target list sorts by season key, then Messier number (D7)."""
    return (target["season_key"], target["number"])


def current_month() -> int:
    return _dt.date.today().month


def timestamp() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Data store: one JSON document, written atomically (D2)
# --------------------------------------------------------------------------- #


def resolve_data_path(cli_value: Optional[str]) -> str:
    """--data wins, then ASTEROIDBELT_DATA, then ~/.asteroidbelt/data.json."""
    raw = cli_value or os.environ.get(ENV_DATA_PATH) or DEFAULT_DATA_PATH
    return os.path.abspath(os.path.expanduser(raw))


def display_path(path: str) -> str:
    """Show paths inside the working directory relative, so transcripts stay clean."""
    try:
        relative = os.path.relpath(path, os.getcwd())
    except ValueError:  # different drive on Windows
        return path
    if relative.startswith(".."):
        return path
    return "." + os.sep + relative if relative != "." else "."


def empty_state() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "config": {"focal_length_mm": None, "aperture_mm": None},
        "eyepieces": [],
        "sessions": [],
        "observations": [],
    }


def _as_int_or_none(value: Any, field: str, path: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataFileError(
            "cannot read data file {}: {} must be a whole number or null".format(
                display_path(path), field))
    return value


def _as_number(value: Any, field: str, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataFileError(
            "cannot read data file {}: {} must be a number".format(
                display_path(path), field))
    return float(value)


def _as_text(value: Any, field: str, path: str) -> str:
    if not isinstance(value, str):
        raise DataFileError(
            "cannot read data file {}: {} must be text".format(
                display_path(path), field))
    return value


def _as_list(value: Any, field: str, path: str) -> List[Any]:
    if not isinstance(value, list):
        raise DataFileError(
            "cannot read data file {}: {} must be a list".format(
                display_path(path), field))
    return value


def load_state(path: str) -> Dict[str, Any]:
    """Read the data file, creating it (with defaults) when it does not exist."""
    if not os.path.exists(path):
        state = empty_state()
        save_state(path, state)
        return state

    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        # Parsed as plain JSON data only: the data file is a document, never an
        # object graph, so a hand-edited file can never execute code on load.
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataFileError(
            "cannot read data file {}: not valid JSON ({} at line {}, column {}); "
            "fix the file or start a new one with --data".format(
                display_path(path), exc.msg, exc.lineno, exc.colno))
    except UnicodeDecodeError:
        raise DataFileError(
            "cannot read data file {}: not valid UTF-8 text; "
            "fix the file or start a new one with --data".format(display_path(path)))
    except OSError as exc:
        raise DataFileError(
            "cannot read data file {}: {}".format(
                display_path(path), exc.strerror or exc))

    if not isinstance(raw, dict):
        raise DataFileError(
            "cannot read data file {}: expected a JSON object at the top level".format(
                display_path(path)))

    version = raw.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise DataFileError(
            "cannot read data file {}: schema_version {} is not supported "
            "(this build understands {})".format(display_path(path), version, SCHEMA_VERSION))

    state = empty_state()
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise DataFileError(
            "cannot read data file {}: config must be an object".format(display_path(path)))
    state["config"]["focal_length_mm"] = _as_int_or_none(
        config.get("focal_length_mm"), "config.focal_length_mm", path)
    state["config"]["aperture_mm"] = _as_int_or_none(
        config.get("aperture_mm"), "config.aperture_mm", path)

    for item in _as_list(raw.get("eyepieces", []), "eyepieces", path):
        if not isinstance(item, dict):
            raise DataFileError(
                "cannot read data file {}: every eyepiece must be an object".format(
                    display_path(path)))
        state["eyepieces"].append({
            "id": _as_int_or_none(item.get("id"), "eyepieces[].id", path),
            "name": _as_text(item.get("name"), "eyepieces[].name", path),
            "focal_length_mm": _as_number(
                item.get("focal_length_mm"), "eyepieces[].focal_length_mm", path),
            "afov_deg": _as_number(item.get("afov_deg"), "eyepieces[].afov_deg", path),
            "created_at": _as_text(item.get("created_at", ""), "eyepieces[].created_at", path),
        })

    for item in _as_list(raw.get("sessions", []), "sessions", path):
        if not isinstance(item, dict):
            raise DataFileError(
                "cannot read data file {}: every session must be an object".format(
                    display_path(path)))
        state["sessions"].append({
            "id": _as_int_or_none(item.get("id"), "sessions[].id", path),
            "date": _as_text(item.get("date"), "sessions[].date", path),
            "title": _as_text(item.get("title"), "sessions[].title", path),
            "created_at": _as_text(item.get("created_at", ""), "sessions[].created_at", path),
        })

    session_ids = {session["id"] for session in state["sessions"]}
    for item in _as_list(raw.get("observations", []), "observations", path):
        if not isinstance(item, dict):
            raise DataFileError(
                "cannot read data file {}: every observation must be an object".format(
                    display_path(path)))
        note = item.get("note")
        messier = _as_text(item.get("messier"), "observations[].messier", path)
        if messier.lstrip("Mm").isdigit() is False or \
                int(messier.lstrip("Mm")) not in CATALOG_BY_NUMBER:
            raise DataFileError(
                "cannot read data file {}: observation {} is not a catalog object "
                "(M1 to M110)".format(display_path(path), messier))
        session_id = _as_int_or_none(
            item.get("session_id"), "observations[].session_id", path)
        if session_id not in session_ids:
            raise DataFileError(
                "cannot read data file {}: observation {} points at session {}, "
                "which does not exist".format(
                    display_path(path), messier, session_id))
        state["observations"].append({
            "id": _as_int_or_none(item.get("id"), "observations[].id", path),
            "session_id": _as_int_or_none(item.get("session_id"), "observations[].session_id", path),
            "messier": _as_text(item.get("messier"), "observations[].messier", path),
            "observed_at": _as_text(
                item.get("observed_at", ""), "observations[].observed_at", path),
            "note": None if note is None else _as_text(note, "observations[].note", path),
        })

    return state


def save_state(path: str, state: Dict[str, Any]) -> None:
    """Write the document atomically: temp file in the same directory, then rename."""
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise DataFileError(
            "cannot write data file {}: {}".format(
                display_path(path), exc.strerror or exc))

    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    handle = None
    temp_path = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory,
            prefix=".asteroidbelt-", suffix=".tmp", delete=False)
        temp_path = handle.name
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise DataFileError(
            "cannot write data file {}: {}".format(
                display_path(path), exc.strerror or exc))
    finally:
        if handle is not None:
            handle.close()
        if temp_path is not None and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def next_id(records: Sequence[Dict[str, Any]]) -> int:
    return max((record.get("id") or 0) for record in records) + 1 if records else 1


# --------------------------------------------------------------------------- #
# Lookups and derived optics (D4)
# --------------------------------------------------------------------------- #


def find_session(state: Dict[str, Any], session_id: int) -> Dict[str, Any]:
    for session in state["sessions"]:
        if session["id"] == session_id:
            return session
    raise UsageError(
        "no session {} exists; list them with: {} session list".format(
            session_id, PROGRAM))


def find_eyepiece(state: Dict[str, Any], eyepiece_id: int) -> Dict[str, Any]:
    for eyepiece in state["eyepieces"]:
        if eyepiece["id"] == eyepiece_id:
            return eyepiece
    raise UsageError(
        "no eyepiece #{}; list them with: {} eyepieces list".format(
            eyepiece_id, PROGRAM))


def session_observations(state: Dict[str, Any], session_id: int) -> List[Dict[str, Any]]:
    return [item for item in state["observations"] if item["session_id"] == session_id]


def observed_numbers(state: Dict[str, Any], session_id: int) -> List[int]:
    numbers = []
    for item in session_observations(state, session_id):
        try:
            numbers.append(int(item["messier"].lstrip("Mm")))
        except ValueError:
            continue
    return sorted(numbers)


def lifetime_observed_numbers(state: Dict[str, Any]) -> List[int]:
    numbers = set()
    for item in state["observations"]:
        try:
            numbers.add(int(item["messier"].lstrip("Mm")))
        except ValueError:
            continue
    return sorted(numbers)


def derive_optics(eyepiece: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """magnification = focal/eyepiece, exit pupil = aperture/magnification, TFOV = afov/mag."""
    telescope_focal = config["focal_length_mm"]
    aperture = config["aperture_mm"]
    magnification = None
    exit_pupil = None
    true_field = None
    if telescope_focal and eyepiece["focal_length_mm"]:
        magnification = telescope_focal / eyepiece["focal_length_mm"]
    if magnification and aperture:
        exit_pupil = aperture / magnification
    if magnification:
        true_field = eyepiece["afov_deg"] / magnification
    return {
        "magnification": magnification,
        "exit_pupil": exit_pupil,
        "true_field": true_field,
    }


def telescope_warning(config: Dict[str, Any]) -> Optional[str]:
    """One warning line, or None when both telescope numbers are known (D5)."""
    if config["focal_length_mm"] is None:
        return (
            "warning: telescope focal length is not set — magnification, exit pupil and "
            "TFOV are shown as {}; set it with: {} config set --focal-length 1200".format(
                DASH, PROGRAM))
    if config["aperture_mm"] is None:
        return (
            "warning: telescope aperture is not set — exit pupil is shown as {}; "
            "set it with: {} config set --aperture 200".format(DASH, PROGRAM))
    return None


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #


def shorten(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def parse_positive_int(value: str, flag: str) -> int:
    try:
        number = int(value.strip())
    except (AttributeError, ValueError):
        raise UsageError(
            '{} needs a positive whole number (got "{}"); '
            "try: {} config set {} 1200".format(flag, value, PROGRAM, flag))
    if number <= 0:
        raise UsageError(
            '{} needs a positive whole number (got "{}"); '
            "try: {} config set {} 1200".format(flag, value, PROGRAM, flag))
    return number


def parse_positive_float(value: str, flag: str, example: str) -> float:
    try:
        number = float(value.strip())
    except (AttributeError, ValueError):
        raise UsageError(
            '{} needs a positive number (got "{}"); try: {}'.format(flag, value, example))
    if number <= 0:
        raise UsageError(
            '{} needs a positive number (got "{}"); try: {}'.format(flag, value, example))
    return number


def parse_identifier(value: str, label: str, example: str) -> int:
    try:
        number = int(str(value).strip())
    except (AttributeError, ValueError):
        raise UsageError(
            '{} needs a whole number (got "{}"); try: {}'.format(label, value, example))
    if number < 1:
        raise UsageError(
            '{} needs a whole number of 1 or more (got "{}"); try: {}'.format(
                label, value, example))
    return number


def normalise_messier(value: str) -> int:
    """Accept "M42", "m42" and "42"; return the catalog number."""
    text = str(value).strip()
    digits = text[1:] if text[:1] in ("M", "m") else text
    if not digits.isdigit():
        raise UsageError(
            '"{}" is not a Messier object; use M1 to M110, e.g. {} session mark 1 M42'.format(
                value, PROGRAM))
    number = int(digits)
    if number < 1 or number > CATALOG_SIZE:
        raise UsageError(
            'M{} is not a Messier object; the catalog holds M1 to M110'.format(number))
    return number


def parse_iso_date(value: str) -> str:
    try:
        return _dt.date.fromisoformat(value.strip()).isoformat()
    except (AttributeError, ValueError):
        raise UsageError(
            '--date needs an ISO date (YYYY-MM-DD, got "{}"); '
            "try: {} session start --date 2025-01-10".format(value, PROGRAM))


def render_note_lines(note: str) -> List[str]:
    """Notes are shown verbatim, wrapped at 72 columns under their target."""
    wrapped = textwrap.wrap(
        note, width=NOTE_WIDTH, break_long_words=True, break_on_hyphens=False)
    return ["    " + line for line in wrapped] if wrapped else []


def emit(lines: Sequence[str], warning: Optional[str] = None) -> int:
    """Successful commands write results to stdout and at most one warning to stderr."""
    if lines:
        sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()
    if warning:
        sys.stderr.write(warning + "\n")
        sys.stderr.flush()
    return EXIT_OK


# --------------------------------------------------------------------------- #
# config show / config set  (F4)
# --------------------------------------------------------------------------- #


def _config_lines(config: Dict[str, Any], path: str) -> List[str]:
    focal = config["focal_length_mm"]
    aperture = config["aperture_mm"]
    lines = [
        "focal length: {}".format("(unset)" if focal is None else "{} mm".format(focal)),
        "aperture: {}".format("(unset)" if aperture is None else "{} mm".format(aperture)),
        "data file: {}".format(display_path(path)),
    ]
    if focal is None or aperture is None:
        lines.append(
            "set them with: {} config set --focal-length 1200 --aperture 200".format(PROGRAM))
    return lines


def cmd_config_show(args: argparse.Namespace) -> int:
    path = resolve_data_path(args.data)
    state = load_state(path)
    return emit(_config_lines(state["config"], path))


def cmd_config_set(args: argparse.Namespace) -> int:
    if args.focal_length is None and args.aperture is None:
        raise UsageError(
            "give at least one of --focal-length or --aperture (positive whole "
            "numbers, or none to unset); try: {} config set --focal-length 1200 "
            "--aperture 200".format(PROGRAM))

    path = resolve_data_path(args.data)
    state = load_state(path)

    if args.focal_length is not None:
        if args.focal_length.strip().lower() == "none":
            state["config"]["focal_length_mm"] = None
        else:
            state["config"]["focal_length_mm"] = parse_positive_int(
                args.focal_length, "--focal-length")
    if args.aperture is not None:
        if args.aperture.strip().lower() == "none":
            state["config"]["aperture_mm"] = None
        else:
            state["config"]["aperture_mm"] = parse_positive_int(
                args.aperture, "--aperture")

    save_state(path, state)
    return emit(_config_lines(state["config"], path))


# --------------------------------------------------------------------------- #
# eyepieces add / list / remove  (F1)
# --------------------------------------------------------------------------- #

EYEPIECE_ROW = "{:>3}  {:<22}  {:>7}  {:>5}  {:>5}  {:>8}  {:>6}"
EYEPIECE_HEADER = EYEPIECE_ROW.format(
    "#", "Name", "FL (mm)", "AFOV", "Mag", "Exit(mm)", "TFOV")

TARGET_ROW = "{:<4}  {:<22}  {:<14}  {:<4}  {:>4}  {:<13}  {:<6}"
TARGET_HEADER = TARGET_ROW.format("M#", "Name", "Type", "Con", "Mag", "Months", "Season")


def _format_number(value: float) -> str:
    """Render 25.0 as "25" and 10.5 as "10.5" without trailing zeros."""
    if float(value) == int(value):
        return str(int(value))
    return ("%.1f" % value).rstrip("0").rstrip(".")


def cmd_eyepieces_add(args: argparse.Namespace) -> int:
    name = (args.name or "").strip()
    if not name:
        raise UsageError(
            '--name is required (1-{} characters, e.g. --name "25mm Plössl")'.format(
                NAME_MAX_CHARS))
    if len(name) > NAME_MAX_CHARS:
        raise UsageError(
            "--name is too long ({} characters, at most {}); "
            'try a shorter name like "25mm Plössl"'.format(len(name), NAME_MAX_CHARS))
    if args.focal_length is None:
        raise UsageError(
            "--focal-length is required (the eyepiece focal length in mm, "
            "e.g. --focal-length 25)")
    if args.afov is None:
        raise UsageError(
            "--afov is required (the apparent field of view in degrees, "
            "e.g. --afov 52)")
    focal_length = parse_positive_float(
        args.focal_length, "--focal-length",
        '{} eyepieces add --focal-length 25 --afov 52'.format(PROGRAM))
    afov = parse_positive_float(
        args.afov, "--afov",
        '{} eyepieces add --focal-length 25 --afov 52'.format(PROGRAM))

    path = resolve_data_path(args.data)
    state = load_state(path)
    for existing in state["eyepieces"]:
        if existing["name"].strip().lower() == name.lower():
            raise UsageError(
                'an eyepiece named "{}" already exists (#{}); pick another name or '
                "remove it with: {} eyepieces remove {}".format(
                    existing["name"], existing["id"], PROGRAM, existing["id"]))

    eyepiece = {
        "id": next_id(state["eyepieces"]),
        "name": name,
        "focal_length_mm": focal_length,
        "afov_deg": afov,
        "created_at": timestamp(),
    }
    state["eyepieces"].append(eyepiece)
    save_state(path, state)

    optics = derive_optics(eyepiece, state["config"])
    confirmation = "added eyepiece #{}: {}".format(eyepiece["id"], eyepiece["name"])
    if optics["magnification"]:
        confirmation += " ({:.0f}x)".format(optics["magnification"])
    return emit([confirmation], telescope_warning(state["config"]))


def cmd_eyepieces_list(args: argparse.Namespace) -> int:
    path = resolve_data_path(args.data)
    state = load_state(path)
    config = state["config"]
    eyepieces = state["eyepieces"]
    if not eyepieces:
        return emit([
            'no eyepieces yet — add one with: {} eyepieces add --name "25mm Plössl" '
            "--focal-length 25 --afov 52".format(PROGRAM)])

    rows = [(eyepiece, derive_optics(eyepiece, config)) for eyepiece in eyepieces]
    if config["focal_length_mm"] is None:
        rows.sort(key=lambda pair: (pair[0]["focal_length_mm"], pair[0]["name"].lower()))
    else:
        rows.sort(key=lambda pair: (-pair[1]["magnification"], pair[0]["name"].lower()))

    lines = [EYEPIECE_HEADER.rstrip(), "-" * len(EYEPIECE_HEADER.rstrip())]
    for eyepiece, optics in rows:
        exit_pupil = DASH if optics["exit_pupil"] is None else "{:.1f}".format(optics["exit_pupil"])
        true_field = (
            DASH if optics["true_field"] is None else "{:.2f}°".format(optics["true_field"]))
        lines.append(EYEPIECE_ROW.format(
            eyepiece["id"],
            shorten(eyepiece["name"], 22),
            _format_number(eyepiece["focal_length_mm"]),
            _format_number(eyepiece["afov_deg"]),
            DASH if optics["magnification"] is None else "{:.0f}x".format(optics["magnification"]),
            exit_pupil,
            true_field,
        ).rstrip())
    return emit(lines, telescope_warning(config))


def cmd_eyepieces_remove(args: argparse.Namespace) -> int:
    if args.eyepiece_id is None:
        raise UsageError(
            "eyepieces remove needs an eyepiece id (see: {} eyepieces list)".format(PROGRAM))
    eyepiece_id = parse_identifier(
        args.eyepiece_id, "eyepieces remove", "eyepieces remove 2")
    path = resolve_data_path(args.data)
    state = load_state(path)
    eyepiece = find_eyepiece(state, eyepiece_id)
    state["eyepieces"] = [
        item for item in state["eyepieces"] if item["id"] != eyepiece_id]
    save_state(path, state)
    return emit(["removed eyepiece #{} ({})".format(eyepiece_id, eyepiece["name"])])


# --------------------------------------------------------------------------- #
# targets [--unobserved] and its filters  (F2, F5)
# --------------------------------------------------------------------------- #


def _active_filters(args: argparse.Namespace) -> Tuple[int, List[str]]:
    """Validate the filters and describe them for the empty-result message."""
    month: Optional[int] = None
    described: List[str] = []
    if args.month is not None:
        text = str(args.month).strip()
        try:
            month = int(text)
        except ValueError:
            raise UsageError(
                '--month needs a whole number from 1 to 12 (got "{}"); '
                "try: {} targets --month 3".format(args.month, PROGRAM))
        if month < 1 or month > 12:
            raise UsageError(
                '--month must be between 1 and 12 (got "{}"); '
                "try: {} targets --month 3".format(args.month, PROGRAM))
        described.append("--month {}".format(month))
    for flag, value in (("--type", args.type),
                        ("--constellation", args.constellation),
                        ("--search", args.search)):
        if value is not None and value.strip():
            described.append("{} {}".format(flag, value.strip()))
    return month or 0, described


def _matches(target: Dict[str, Any], month: int, args: argparse.Namespace) -> bool:
    if month and month not in target["best_months"]:
        return False
    if args.type and args.type.strip():
        needle = args.type.strip().lower()
        if needle not in target["type"].lower():
            return False
    if args.constellation and args.constellation.strip():
        needle = args.constellation.strip().lower()
        abbr = CONSTELLATION_ABBR[target["constellation"]].lower()
        if needle not in target["constellation"].lower() and needle not in abbr:
            return False
    if args.search and args.search.strip():
        needle = args.search.strip().lower()
        if needle not in target["messier"].lower() and needle not in target["name"].lower():
            return False
    return True


def render_target_table(targets: Sequence[Dict[str, Any]], month: int) -> List[str]:
    lines = [TARGET_HEADER.rstrip(), "-" * len(TARGET_HEADER.rstrip())]
    for target in targets:
        lines.append(TARGET_ROW.format(
            target["messier"],
            shorten(target["name"], 22),
            TYPE_LABEL[target["type"]],
            CONSTELLATION_ABBR[target["constellation"]],
            "{:.1f}".format(target["magnitude"]),
            render_month_range(target["best_months"]),
            "yes" if month and month in target["best_months"] else "-",
        ).rstrip())
    return lines


def cmd_targets(args: argparse.Namespace) -> int:
    path = resolve_data_path(args.data)
    state = load_state(path)
    month, described = _active_filters(args)
    filters = " ".join(described)

    pool: Sequence[Dict[str, Any]] = MESSIER_CATALOG
    if args.unobserved:
        seen = set(lifetime_observed_numbers(state))
        pool = [target for target in MESSIER_CATALOG if target["number"] not in seen]

    matching = sorted(
        (target for target in pool if _matches(target, month, args)),
        key=season_sort_key)

    if not matching:
        if args.unobserved and not pool:
            return emit([
                "all {} Messier objects have been observed".format(CATALOG_SIZE)])
        message = "no targets match{} — widen or clear the filters".format(
            " " + filters if filters else " the current filters")
        return emit([message])

    lines = render_target_table(matching, month)
    if args.unobserved:
        lines.append("{} of {} unobserved across {} session{}".format(
            len(matching), CATALOG_SIZE, len(state["sessions"]),
            "" if len(state["sessions"]) == 1 else "s"))
    else:
        lines.append("{} of {} targets".format(len(matching), CATALOG_SIZE))
    return emit(lines)


# --------------------------------------------------------------------------- #
# session start / mark / unmark / show / list  (F3, F6)
# --------------------------------------------------------------------------- #

SESSION_ROW = "{:>3}  {:<10}  {:<24}  {:>8}  {:>9}"
SESSION_HEADER = SESSION_ROW.format("ID", "Date", "Title", "Observed", "Remaining")

REMAINING_ROW = "  {:<4}  {:<22}  {}"


def cmd_session_start(args: argparse.Namespace) -> int:
    title = (args.title or "").strip()
    if not title:
        raise UsageError(
            '--title is required (1-{} characters, e.g. --title "Cold night")'.format(
                TITLE_MAX_CHARS))
    if len(title) > TITLE_MAX_CHARS:
        raise UsageError(
            "--title is too long ({} characters, at most {}); "
            'try a shorter title like "Cold night"'.format(len(title), TITLE_MAX_CHARS))
    date = parse_iso_date(args.date) if args.date else _dt.date.today().isoformat()

    path = resolve_data_path(args.data)
    state = load_state(path)
    session = {
        "id": next_id(state["sessions"]),
        "date": date,
        "title": title,
        "created_at": timestamp(),
    }
    state["sessions"].append(session)
    save_state(path, state)
    return emit([
        'started session {} — {} "{}"'.format(session["id"], session["date"], session["title"]),
        "mark a target with: {} session mark {} M31".format(PROGRAM, session["id"]),
    ])


def cmd_session_mark(args: argparse.Namespace) -> int:
    if args.session is None:
        raise UsageError(
            "session mark needs a session id (see: {} session list)".format(PROGRAM))
    if args.messier is None:
        raise UsageError(
            "session mark needs a Messier object (e.g. {} session mark 1 M42)".format(PROGRAM))
    session_id = parse_identifier(
        args.session, "session mark (session id)", "session mark 1 M42")
    number = normalise_messier(args.messier)
    note = args.note
    if note is not None:
        note = note.strip()
        if not note:
            note = None
        elif len(note) > NOTE_MAX_CHARS:
            raise UsageError(
                "--note is {} characters, the maximum is {}; "
                "try a shorter note".format(len(note), NOTE_MAX_CHARS))

    path = resolve_data_path(args.data)
    state = load_state(path)
    find_session(state, session_id)
    messier = "M{}".format(number)
    for item in session_observations(state, session_id):
        if item["messier"] == messier:
            raise UsageError(
                "{} is already marked in session {}; "
                "unmark it with: {} session unmark {} {}".format(
                    messier, session_id, PROGRAM, session_id, messier))

    state["observations"].append({
        "id": next_id(state["observations"]),
        "session_id": session_id,
        "messier": messier,
        "observed_at": timestamp(),
        "note": note,
    })
    save_state(path, state)
    observed = len(observed_numbers(state, session_id))
    return emit(["marked {} in session {} ({} of {} observed)".format(
        messier, session_id, observed, CATALOG_SIZE)])


def cmd_session_unmark(args: argparse.Namespace) -> int:
    if args.session is None:
        raise UsageError(
            "session unmark needs a session id (see: {} session list)".format(PROGRAM))
    if args.messier is None:
        raise UsageError(
            "session unmark needs a Messier object (e.g. {} session unmark 1 M42)".format(
                PROGRAM))
    session_id = parse_identifier(
        args.session, "session unmark (session id)", "session unmark 1 M42")
    messier = "M{}".format(normalise_messier(args.messier))

    path = resolve_data_path(args.data)
    state = load_state(path)
    find_session(state, session_id)
    remaining = []
    removed = False
    for item in state["observations"]:
        if item["session_id"] == session_id and item["messier"] == messier:
            removed = True
            continue
        remaining.append(item)
    if not removed:
        raise UsageError(
            "{} is not marked in session {}; mark it with: {} session mark {} {}".format(
                messier, session_id, PROGRAM, session_id, messier))
    state["observations"] = remaining
    save_state(path, state)
    observed = len(observed_numbers(state, session_id))
    return emit(["unmarked {} in session {} ({} of {} observed)".format(
        messier, session_id, observed, CATALOG_SIZE)])


def cmd_session_show(args: argparse.Namespace) -> int:
    if args.session is None:
        raise UsageError(
            "session show needs a session id (see: {} session list)".format(PROGRAM))
    session_id = parse_identifier(
        args.session, "session show (session id)", "session show 1")

    path = resolve_data_path(args.data)
    state = load_state(path)
    session = find_session(state, session_id)
    marks = sorted(
        session_observations(state, session_id),
        key=lambda item: int(item["messier"].lstrip("Mm")))
    observed = len(observed_numbers(state, session_id))
    lines = [
        'session {} — {} "{}"'.format(session["id"], session["date"], session["title"]),
        "observed {} / remaining {}".format(observed, CATALOG_SIZE - observed),
    ]

    if not marks:
        lines.append("mark one with: {} session mark {} M31".format(PROGRAM, session_id))
    else:
        lines.append("")
        lines.append("Observed")
        for item in marks:
            target = CATALOG_BY_NUMBER[int(item["messier"].lstrip("Mm"))]
            lines.append("  {}  {}".format(target["messier"], target["name"]))
            if item["note"]:
                lines.extend(render_note_lines(item["note"]))

    marked = {item["messier"] for item in marks}
    remaining = [target for target in MESSIER_CATALOG if target["messier"] not in marked]
    lines.append("")
    if not remaining:
        lines.append("all {} Messier objects observed — nothing left".format(CATALOG_SIZE))
    else:
        lines.append("Remaining")
        for target in sorted(remaining, key=season_sort_key):
            lines.append(REMAINING_ROW.format(
                target["messier"],
                target["name"],
                render_month_range(target["best_months"])))
    return emit(lines)


def cmd_session_list(args: argparse.Namespace) -> int:
    path = resolve_data_path(args.data)
    state = load_state(path)
    if not state["sessions"]:
        return emit([
            "no sessions yet — start one with: {} session start".format(PROGRAM)])

    sessions = sorted(state["sessions"], key=lambda session: (session["date"], session["id"]))
    lines = [SESSION_HEADER.rstrip(), "-" * len(SESSION_HEADER.rstrip())]
    for session in sessions:
        observed = len(observed_numbers(state, session["id"]))
        lines.append(SESSION_ROW.format(
            session["id"],
            session["date"],
            shorten(session["title"], 24),
            observed,
            CATALOG_SIZE - observed,
        ).rstrip())
    total = len(lifetime_observed_numbers(state))
    lines.append("{} session{} — {} of {} Messier objects observed".format(
        len(sessions), "" if len(sessions) == 1 else "s", total, CATALOG_SIZE))
    return emit(lines)


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #

EPILOG = """\
examples:
  {prog} config set --focal-length 1200 --aperture 200
  {prog} eyepieces add --name "25mm Plössl" --focal-length 25 --afov 52
  {prog} eyepieces list
  {prog} targets --month 4 --type galaxy
  {prog} session start --date 2025-01-10 --title "Cold night"
  {prog} session mark 1 M42 --note "Trapezium split at 48x"
  {prog} session show 1
  {prog} targets --unobserved
  {prog} session list

state:
  one JSON document, chosen by --data PATH or $ASTEROIDBELT_DATA,
  default ~/.asteroidbelt/data.json

exit codes:
  0 success, 1 data-file failure, 2 usage or validation error
""".format(prog=PROGRAM)


class _Parser(argparse.ArgumentParser):
    """argparse, but every failure becomes one ``error:`` line with exit code 2."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROGRAM,
        description="AsteroidBelt — eyepiece magnifications, Messier viewing windows "
                    "and per-session target mark-off.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--data", metavar="PATH",
        help="JSON data file (default: $ASTEROIDBELT_DATA or ~/.asteroidbelt/data.json)")
    parser.add_argument(
        "--version", action="version", version="{} {}".format(PROGRAM, __version__))
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # config -----------------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config", help="show or set the telescope focal length and aperture",
        description="Show or set the telescope numbers every derived eyepiece "
                    "column depends on.")
    config_sub = config_parser.add_subparsers(dest="config_command", metavar="ACTION")
    show_parser = config_sub.add_parser(
        "show", help="print focal length, aperture and the data-file path",
        description="Print focal length, aperture and the effective data-file path.")
    show_parser.set_defaults(handler=cmd_config_show)
    set_parser = config_sub.add_parser(
        "set", help="set focal length and/or aperture (positive whole mm, or 'none')",
        description="Set focal length and/or aperture. Values are positive whole "
                    "numbers of millimetres; 'none' unsets a value.")
    set_parser.add_argument("--focal-length", metavar="MM",
                            help="telescope focal length in mm, or none to unset")
    set_parser.add_argument("--aperture", metavar="MM",
                            help="telescope aperture in mm, or none to unset")
    set_parser.set_defaults(handler=cmd_config_set)

    # eyepieces --------------------------------------------------------------
    eyepieces_parser = subparsers.add_parser(
        "eyepieces", help="add, list and remove eyepieces",
        description="Maintain the eyepiece case; derived columns come from the "
                    "configured telescope.")
    eyepieces_sub = eyepieces_parser.add_subparsers(
        dest="eyepieces_command", metavar="ACTION")
    add_parser = eyepieces_sub.add_parser(
        "add", help="add an eyepiece",
        description="Add one eyepiece: name, focal length in mm and apparent field "
                    "of view in degrees.")
    add_parser.add_argument("--name", metavar="NAME", help="eyepiece name, e.g. \"25mm Plössl\"")
    add_parser.add_argument("--focal-length", metavar="MM",
                            help="eyepiece focal length in mm, e.g. 25")
    add_parser.add_argument("--afov", metavar="DEG",
                            help="apparent field of view in degrees, e.g. 52")
    add_parser.set_defaults(handler=cmd_eyepieces_add)
    list_parser = eyepieces_sub.add_parser(
        "list", help="list eyepieces with magnification, exit pupil and TFOV",
        description="List the eyepiece case, sorted by magnification descending.")
    list_parser.set_defaults(handler=cmd_eyepieces_list)
    remove_parser = eyepieces_sub.add_parser(
        "remove", help="remove an eyepiece by id",
        description="Remove one eyepiece by its id (see eyepieces list).")
    remove_parser.add_argument("eyepiece_id", nargs="?", metavar="ID",
                               help="id of the eyepiece to remove")
    remove_parser.set_defaults(handler=cmd_eyepieces_remove)

    # targets ----------------------------------------------------------------
    targets_parser = subparsers.add_parser(
        "targets", help="print Messier viewing windows",
        description="Print the Messier catalog as an 80-column viewing-window table, "
                    "ordered by season key then Messier number.")
    targets_parser.add_argument("--month", metavar="N",
                                help="only objects in season in month N (1-12)")
    targets_parser.add_argument("--type", metavar="TYPE",
                                help="only objects whose type matches, e.g. galaxy")
    targets_parser.add_argument("--constellation", metavar="NAME",
                                help="only objects in this constellation, e.g. And")
    targets_parser.add_argument("--search", metavar="TEXT",
                                help="case-insensitive substring of Messier number or name")
    targets_parser.add_argument("--unobserved", action="store_true",
                                help="only objects never observed in any session")
    targets_parser.set_defaults(handler=cmd_targets)

    # session ----------------------------------------------------------------
    session_parser = subparsers.add_parser(
        "session", help="start, mark, show and list observing sessions",
        description="Track an observing session and mark Messier targets off.")
    session_sub = session_parser.add_subparsers(dest="session_command", metavar="ACTION")

    start_parser = session_sub.add_parser(
        "start", help="start a dated session and print its id",
        description="Start a session. --date defaults to today.")
    start_parser.add_argument("--date", metavar="YYYY-MM-DD", help="ISO date, defaults to today")
    start_parser.add_argument("--title", metavar="TEXT", help="session title, 1-60 characters")
    start_parser.set_defaults(handler=cmd_session_start)

    mark_parser = session_sub.add_parser(
        "mark", help="mark a Messier target observed in a session",
        description="Mark one Messier object observed in a session, with an optional "
                    "note of up to 200 characters.")
    mark_parser.add_argument("session", nargs="?", metavar="SESSION", help="session id")
    mark_parser.add_argument("messier", nargs="?", metavar="Mxx", help="Messier object, e.g. M42")
    mark_parser.add_argument("--note", metavar="TEXT",
                             help="optional note, at most 200 characters")
    mark_parser.set_defaults(handler=cmd_session_mark)

    unmark_parser = session_sub.add_parser(
        "unmark", help="unmark a Messier target in a session",
        description="Move a target back to the remaining list and drop its note.")
    unmark_parser.add_argument("session", nargs="?", metavar="SESSION", help="session id")
    unmark_parser.add_argument("messier", nargs="?", metavar="Mxx", help="Messier object, e.g. M42")
    unmark_parser.set_defaults(handler=cmd_session_unmark)

    show_parser = session_sub.add_parser(
        "show", help="show one session: counts, observed notes, remaining targets",
        description="Print the session scoreboard: counts, the observed list with "
                    "notes, and the remaining targets in season order.")
    show_parser.add_argument("session", nargs="?", metavar="SESSION", help="session id")
    show_parser.set_defaults(handler=cmd_session_show)

    list_sessions_parser = session_sub.add_parser(
        "list", help="summarise every session with per-session counts",
        description="One row per session, sorted by date then id, plus totals.")
    list_sessions_parser.set_defaults(handler=cmd_session_list)

    return parser


def _configure_streams() -> None:
    """Never die on a non-UTF-8 console: substitute instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # already-wrapped or closed stream
            continue


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None:
            parser.print_help()
            return EXIT_OK
        handler = getattr(args, "handler", None)
        if handler is None:
            # e.g. "asteroidbelt config" with no action: print that command's help.
            parser.parse_args([args.command, "--help"])
            return EXIT_OK
        return handler(args)
    except AsteroidBeltError as exc:
        sys.stderr.write("error: {}\n".format(exc.message))
        sys.stderr.flush()
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
