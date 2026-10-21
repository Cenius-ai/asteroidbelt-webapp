# Design direction — AsteroidBelt

Committed for this build; every surface (the tool's output, the docs, the
transcript) consumes these tokens. This is the source of truth for the palette
and the type ramp — do not re-derive them elsewhere.

## Surface

| token | value | use |
| --- | --- | --- |
| `--surface` | `oklch(0.17 0.01 276)` / `#15161c` | terminal dark — the only honest surface for a CLI |
| `--surface-raised` | `oklch(0.22 0.012 276)` | documentation code blocks |
| `--ink` | `oklch(0.93 0.005 276)` / `#e8e8ee` | body text |
| `--ink-muted` | `oklch(0.72 0.008 276)` / `#a9aab5` | rules, secondary labels |
| `--accent` | `oklch(0.58 0.12 276)` / `#6872c0` | the ONE accent: product identity and primary status |
| `--warn` | `oklch(0.75 0.13 85)` / `#d8a94a` | the single degraded-mode `warning:` line |

`--accent` never carries meaning on its own: the `Season` column says the word
`yes`, and every marker also appears as `-`. Colour, where a colour-capable
surface exists, is decoration on top of a signal that already reads in plain
ASCII.

## Type

| role | token |
| --- | --- |
| everything | system monospace (`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`) |
| ramp | 12 / 13 / 14 / 16 px; table rows and headings share one size, one weight |

No display face, no second family, no italics for emphasis.

## Shape

* No chrome: no boxes, no shadows, no rounded corners, no gradients.
* Separators are `-` rules and `|`-free aligned columns; the widest table is
  authored to 80 columns and every row is `rstrip`-ed so a diff never shows
  trailing whitespace.
* Density: compact. One blank line between sections, never two.
* Alignment: numbers right, text left, the `#`/`M#` identifier first.
* Output is plain ASCII plus `—` (dash for a value that cannot be derived) and
  `–` (a collapsing month range). No ANSI colour anywhere: the tool must read
  identically when piped, redirected or diffed.
