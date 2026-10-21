#!/usr/bin/env bash
# AsteroidBelt installer.
#
# Installs project-level dependencies only (never system packages), verifies the
# tool imports, optionally puts the `asteroidbelt` console script on PATH and
# seeds a demo data file the first time it runs.  It EXITS — starting the tool is
# a separate command (`asteroidbelt targets`).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
DATA_FILE="${ASTEROIDBELT_DATA:-${HOME:-.}/.asteroidbelt/data.json}"

"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 9):
    sys.exit("error: AsteroidBelt needs Python 3.9 or newer (found {})".format(
        sys.version.split()[0]))
print("python: {}".format(sys.version.split()[0]))
PY

# Refresh the packaging tools when the machine allows it; the tool itself has no
# third-party runtime dependencies, so an offline box is fine.
"$PYTHON" -m pip install --upgrade --quiet pip setuptools wheel >/dev/null 2>&1 ||
    echo "note: could not refresh pip/setuptools/wheel (offline?); continuing" >&2

# The test runner is the only pinned dependency.
if ! "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
    "$PYTHON" -m pip install --quiet -r requirements.txt
fi

# Optional console script: `asteroidbelt ...` instead of `python3 asteroidbelt.py ...`.
if ! command -v asteroidbelt >/dev/null 2>&1; then
    "$PYTHON" -m pip install --quiet --no-build-isolation -e . ||
        echo "note: could not install the console script; run the tool as: python3 asteroidbelt.py" >&2
fi

"$PYTHON" -m compileall -q asteroidbelt.py
"$PYTHON" -c "import asteroidbelt" # fails loudly if a module is missing

seed_data_file() {
    local recent older
    recent="$("$PYTHON" -c 'import datetime as d; print((d.date.today() - d.timedelta(days=9)).isoformat())')"
    older="$("$PYTHON" -c 'import datetime as d; print((d.date.today() - d.timedelta(days=23)).isoformat())')"

    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" config set --focal-length 1200 --aperture 200 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" eyepieces add --name "32mm Plössl" --focal-length 32 --afov 50 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" eyepieces add --name "25mm Plössl" --focal-length 25 --afov 52 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" eyepieces add --name "12mm Radian" --focal-length 12 --afov 60 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" eyepieces add --name "9mm Ortho" --focal-length 9 --afov 42 >/dev/null

    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session start --date "$older" --title "Back garden, first night" >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 1 M31 --note "Core obvious at 38x; dust lane held with averted vision." >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 1 M42 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 1 M45 --note "Naked-eye object; the whole cluster fits the 32mm field." >/dev/null

    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session start --date "$recent" --title "Cold night, steady air" >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 2 M44 --note "Beehive resolved into two dozen stars at 100x." >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 2 M67 >/dev/null
    "$PYTHON" asteroidbelt.py --data "$DATA_FILE" session mark 2 M81 --note "Both cores held at 48x; M82 close by in the same field." >/dev/null
}

if [ ! -f "$DATA_FILE" ]; then
    if seed_data_file; then
        echo "seeded demo data: $DATA_FILE"
    else
        echo "note: could not seed demo data at $DATA_FILE (read-only home?); use --data PATH" >&2
    fi
else
    echo "data file already present, left untouched: $DATA_FILE"
fi

echo "Setup complete. Try:"
echo "  python3 asteroidbelt.py config show"
echo "  python3 asteroidbelt.py eyepieces list"
echo "  python3 asteroidbelt.py targets --month 4 --type galaxy"
echo "  python3 asteroidbelt.py session list"
