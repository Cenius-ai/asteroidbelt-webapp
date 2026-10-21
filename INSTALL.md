# Installing AsteroidBelt

AsteroidBelt is one Python file with **no third-party runtime dependencies**.
Python 3.9 or newer is the only prerequisite.

## 1. Prerequisites (installed by you, not by this project)

| requirement | why |
| --- | --- |
| Python **3.9+** (`python3 --version`) | the tool itself; it uses only the standard library |
| `pip` for that interpreter | only needed to install the optional console script and the pinned test runner |

Nothing else — no compiler, no database, no system libraries, no network access
at runtime.

## 2. Install the project dependencies

```bash
bash install.sh
```

`install.sh` is idempotent and does exactly this, then **exits** (it never starts
the tool):

1. checks the Python version is 3.9 or newer;
2. refreshes `pip`, `setuptools` and `wheel` when the machine allows it (offline
   is fine, it only warns);
3. installs `requirements.txt` — that file pins one package, the test runner
   `pytest==9.1.1` — skipping the install when `pytest` is already importable;
4. installs the optional `asteroidbelt` console script through
   `pip install -e . --no-build-isolation`, so you can type `asteroidbelt`
   instead of `python3 asteroidbelt.py`;
5. compiles and imports `asteroidbelt.py` so a broken checkout fails here, not
   in the middle of an observing run;
6. seeds a demo data file **only when it does not exist yet**, so re-running the
   installer never touches your log.

To install without the installer script:

```bash
python3 -m pip install -r requirements.txt    # test runner only
python3 -m pip install -e . --no-build-isolation   # optional console script
```

## 3. Seed (demo) data

The installer seeds `~/.asteroidbelt/data.json` the first time it runs: a
1200 mm / 200 mm telescope, four eyepieces, and two recent sessions with a few
Messier marks and notes, so every command has something to show.

To seed a different file yourself, or to start over:

```bash
python3 asteroidbelt.py --data /tmp/ab-demo.json config set --focal-length 1200 --aperture 200
python3 asteroidbelt.py --data /tmp/ab-demo.json eyepieces add --name "25mm Plössl" --focal-length 25 --afov 52
python3 asteroidbelt.py --data /tmp/ab-demo.json session start --title "Cold night"
```

The seeder in `install.sh` only runs when the data file is absent, so it is safe
to run it as often as you like.

## 4. Run

```bash
python3 asteroidbelt.py --help          # or simply: asteroidbelt --help
python3 asteroidbelt.py config show
python3 asteroidbelt.py eyepieces list
python3 asteroidbelt.py targets --month 4 --type galaxy
python3 asteroidbelt.py session list
```

The data file is chosen by `--data PATH`, else `$ASTEROIDBELT_DATA`, else
`~/.asteroidbelt/data.json`. It is created on first use and is plain,
indented JSON.

## 5. Test

```bash
python3 -m pytest -q
```

48 tests, no network, no services; every test runs the real command in a
subprocess against a temporary data file.

## 6. Demo transcript

```bash
bash demo.sh                 # print the transcript
bash demo.sh docs/demo.txt   # regenerate the committed transcript
```

`demo.sh` runs the whole tool end to end against a throwaway data file inside a
temporary directory, so it never reads or writes your own log.

## Uninstall

```bash
python3 -m pip uninstall asteroidbelt      # only if you installed the console script
rm -rf ~/.asteroidbelt                     # your data file
```
