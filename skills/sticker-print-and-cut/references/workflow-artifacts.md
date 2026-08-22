# Workflow artifacts and verification

Read this reference when interpreting generated files, diagnosing preparation or dry-run failures, or confirming that print and cut coordinates agree.

## Coordinate and input contract

Millimeters are canonical. Pixels are used only for source-mask analysis and raster rendering. Page-space millimeter geometry is shared by the embedded artwork, cut paths, print raster, preview, registration marks, metadata, and verifier.

Transparent PNG is the reliable input format because alpha directly defines foreground. Source DPI metadata determines physical scale when artwork has not been normalized. If DPI is missing or unreliable, pass `--input-dpi` explicitly and report the assumption.

Fully opaque input falls back to foreground estimation based on color distance from the median border color. That heuristic is recorded in metadata and can split shadows, checkerboards, gradients, or background texture into false stickers. Do not accept it for a physical cut without checking component count and every contour; prefer a genuinely transparent source.

## Output contract

`prepare` creates:

```text
WORK/output/
  print-sheet.png
  cut-sheet.svg
  preview.png
  metadata.json
  verify-report.json
  dry-run/
    status.json
```

- `print-sheet.png` is the page-sized print artifact containing artwork and registration marks, without blade contours. Print only this file at Actual Size.
- `cut-sheet.svg` is the physical millimeter cut document. It has equal physical dimensions and `viewBox` values, embeds the raster artwork, and contains `Print`, `Regmarks`, and `Cut` Inkscape layers.
- `preview.png` is visual evidence only. Red lines are blade contours, magenta lines participate in an overlap or edge-touch conflict, and the cyan rectangle is the conservative registration-safe area. Never print it.
- `metadata.json` records component measurements, complete contour coordinates, coordinate transforms, registration positions, cut-safety conflicts, warnings, and artifact hashes.
- `verify-report.json` records each invariant and the overall `verified` result.

Never edit, resize, or reposition one generated artifact independently. Rerun preparation so every representation remains aligned.

## Registration convention and safe area

The bundled generator emits the standard three-point convention expected by the upstream extension:

- 5 mm top-left square;
- 20 mm top-right and bottom-left L-shaped marks;
- 0.3 mm strokes;
- SVG IDs `regmark-tl`, `regmark-tr`, and `regmark-bl`.

The `Regmarks` and `Print` layer names allow the upstream driver to ignore non-cut content. The layout intentionally requires every contour to fit in a conservative rectangle inset by the full 20 mm registration arms. A safe-area failure is a hard stop; never move a contour into the mark-exclusion region or silently shrink it.

## Verification coverage

Run:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py verify WORK/output
```

Verification checks:

- print page pixels and DPI;
- SVG physical units and `viewBox`;
- required layers and registration IDs;
- expected count and closed contours;
- pairwise overlap and edge touching;
- metadata bounding boxes and safe-area containment;
- coordinate scale agreement;
- hashes of the generated artifacts.

It rewrites `verify-report.json` and exits nonzero on disagreement. A stale hash usually means an artifact changed after preparation; regenerate the complete set instead of accepting the modified file.

## What the hardware-free dry run proves

Run:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py silhouette-dry-run WORK/output/cut-sheet.svg \
  --driver /absolute/path/to/inkscape-silhouette/sendto_silhouette.py
```

Use `--python /absolute/path/to/python` when the driver needs Inkscape's configured interpreter. Alternatively set `INKSCAPE_SILHOUETTE_DRIVER` to avoid repeating the driver path.

Current upstream waits for a real optical-sensor response whenever registration search is enabled, even in its own dry-run mode. The bundled wrapper therefore performs two hardware-free passes:

1. A registration probe confirms that the SVG marks are detected and captures the registration command. The specific no-sensor stop is expected without hardware.
2. A complete blade-command pass disables the optical search but applies the same negative registration-origin offset that a successful scan would apply.

The wrapper passes only when the blade pass parses the paths, emits commands, and reaches ready status, while the registration probe reaches either real success or the expected no-hardware sensor stop. No cutter is contacted.

Detailed diagnostics are written under `WORK/output/dry-run/`:

```text
status.json
silhouette.log
cutter-commands.bin
registration-probe.log
registration-commands.bin
stdout.txt
stderr.txt
```

Dry-run success does not prove device discovery, BLE/USB communication, optical sensing, mat placement, blade installation, pressure, speed, depth, or observed cut quality.
