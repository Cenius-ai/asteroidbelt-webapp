#!/usr/bin/env bash
# AsteroidBelt demo — drives the whole tool end to end, non-interactively,
# against a throwaway data file in a temporary directory so nothing personal is
# read or written.
#
#   bash demo.sh                  # print the transcript to the terminal
#   bash demo.sh docs/demo.txt    # regenerate the committed transcript
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

OUT_ABS=""
if [ "$#" -ge 1 ] && [ -n "$1" ]; then
    case "$1" in
        /*) OUT_ABS="$1" ;;
        *) OUT_ABS="$PWD/$1" ;;
    esac
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ln -s "$ROOT/asteroidbelt.py" "$WORK/asteroidbelt.py"
cd "$WORK"

RECENT="$("${PYTHON:-python3}" -c 'import datetime as d; print((d.date.today() - d.timedelta(days=3)).isoformat())')"
OLDER="$("${PYTHON:-python3}" -c 'import datetime as d; print((d.date.today() - d.timedelta(days=17)).isoformat())')"

ab() {
    local display="" argument
    for argument in "$@"; do
        case "$argument" in
            *" "*) display="$display \"$argument\"" ;;
            *) display="$display $argument" ;;
        esac
    done
    printf '$ asteroidbelt%s\n' "$display"
    "${PYTHON:-python3}" asteroidbelt.py --data demo.json "$@"
    printf '\n'
}

transcript() {
    printf '# AsteroidBelt demo — generated with: bash demo.sh docs/demo.txt\n'
    printf '# Every command runs against a throwaway ./demo.json data file.\n\n'

    ab config show
    ab config set --focal-length 1200 --aperture 200

    ab eyepieces add --name "32mm Plössl" --focal-length 32 --afov 50
    ab eyepieces add --name "25mm Plössl" --focal-length 25 --afov 52
    ab eyepieces add --name "12mm Radian" --focal-length 12 --afov 60
    ab eyepieces add --name "9mm Ortho" --focal-length 9 --afov 42
    ab eyepieces list

    ab targets --month 12 --type nebula
    ab targets --search orion
    ab targets --type galaxy --constellation And

    ab session start --date "$OLDER" --title "Back garden, first clear night"
    ab session mark 1 M42 --note "Trapezium split cleanly at 100x; wings obvious."
    ab session mark 1 M43
    ab session mark 1 M45 --note "Whole cluster fits the 32mm field at 38x."
    ab session show 1

    ab session start --date "$RECENT" --title "Cold night, steady seeing"
    ab session mark 2 M31 --note "Dust lane held with averted vision at 48x."
    ab session mark 2 M44 --note "Beehive resolved into two dozen stars at 100x."
    ab session show 2

    ab session list
    ab targets --unobserved --constellation Ori
    ab session unmark 2 M44
    ab session show 2
}

if [ -n "$OUT_ABS" ]; then
    transcript | tee "$OUT_ABS"
    printf 'wrote %s\n' "$OUT_ABS" >&2
else
    transcript
fi
