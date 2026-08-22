# sticker-cutter

`sticker-cutter` is a portable Codex skill and command-line workflow for raster sticker Print & Cut, currently verified on the Silhouette Cameo 5 Alpha. It detects disconnected stickers from a PNG, normalizes their physical size, derives smooth physical cut contours, adds a configurable border, and writes mutually aligned print, cut, preview, and diagnostic artifacts.

The canonical coordinate system is millimeters. Pixels are used only for source-mask analysis and output rendering. The same page-space geometry drives the embedded SVG artwork, cut paths, print raster, preview, registration marks, and metadata.

![Generated cartoon train stickers with unsafe contour pairs highlighted in magenta](examples/train-stickers/output/preview.png)

The example above starts with an AI-generated transparent raster sheet and detects eight separate stickers. Its 2 mm borders produce five intersecting contour pairs, so the workflow highlights the affected contours in magenta, marks regeneration as required, and blocks printing or cutting.

## Install

The complete installable skill lives in `skills/sticker-print-and-cut/`, including its executable code and references. Copy that directory into the Codex skills directory or install it from this repository with the skill installer. The bundled `scripts/sticker_cut_cli.py` contains inline `uv` dependencies and can run from any working directory; it does not require this repository after installation.

For repository development, Python 3.10 or newer is required. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

To exercise `inkscape-silhouette` from the project environment as well, install the optional CLI dependencies:

```bash
uv sync --extra dev --extra silhouette
```

The upstream hardware driver still needs its own checkout and an interpreter that can import Inkscape's `inkex`. On macOS, follow the skill's [installation runbook](skills/sticker-print-and-cut/references/macos-install.md). It covers Homebrew `libusb`, BLE's `bleak` dependency, the normal `install_osx.sh` path, and the matching-external-Python fallback for newer macOS systems that kill Inkscape's embedded helper interpreter.

The upstream `sendto_silhouette.py` must come from an installed or checked-out copy of [fablabnbg/inkscape-silhouette](https://github.com/fablabnbg/inkscape-silhouette). Before a direct BLE session, close Silhouette Studio so its Bluetooth helper releases the cutter. For chained test and production cuts, use `--endposition=start` on the test; after any registration timeout, manually unload and reload the mat before retrying. See the [connection and registration runbook](skills/sticker-print-and-cut/references/silhouette-connections.md).

## Normalize physical sticker size

Image-generation models control pixels, not centimeters. To make every detected sticker 20 mm on its longest artwork side, resize and repack the components before adding the fixed-width cut border:

```bash
uv run sticker-cut normalize generated.png \
  --output normalized.png \
  --sticker-size 20mm \
  --size-basis artwork \
  --border 2mm \
  --clearance 2mm \
  --page letter \
  --dpi 300
```

`--size-basis artwork` excludes the cut border from the requested size. `--size-basis finished` includes it: a 20 mm finished sticker with a 2 mm border gets a 16 mm longest artwork side before the contour offset. Aspect ratio is preserved, every component is scaled independently, and the packing stage fails instead of silently shrinking stickers when the requested count and size do not fit. The companion `normalized.normalization.json` records measured source/output bounds and physical sizes.

## Prepare a sheet

Transparent PNG input is recommended. Its alpha channel is deterministic and avoids guessing the background. Source DPI metadata defines the physical size; without reliable metadata the CLI assumes 300 DPI and records a warning. Override that explicitly when needed.

```bash
uv run sticker-cut prepare stickers.png --border 2mm --page letter
```

Useful controls include:

```bash
uv run sticker-cut prepare stickers.png \
  --output output \
  --input-dpi 300 \
  --dpi 300 \
  --min-area 1.0 \
  --closing 0.3mm \
  --simplify 0.12mm
```

The command creates:

```text
output/
  print-sheet.png
  cut-sheet.svg
  preview.png
  metadata.json
  verify-report.json
  dry-run/
    status.json
```

- `print-sheet.png` is a page-sized 300 DPI image containing artwork and registration marks, with no cut-line overlay. Print at **100% / Actual Size** and disable printer scaling.
- `cut-sheet.svg` uses physical `mm` dimensions and an equal-valued `viewBox`. It contains `Print`, `Regmarks`, and `Cut` Inkscape layers. Its original raster artwork is embedded, so the file is portable.
- `preview.png` overlays red blade contours and a cyan conservative safe-area rectangle for visual review. Contours involved in an overlap or edge-touch conflict are redrawn in magenta. Do not print it.
- `metadata.json` records coordinate matrices, component statistics, full contour coordinates, registration positions, cut-safety diagnostics, warnings, and artifact hashes.

The implementation uses the current upstream standard three-point mark convention: a 5 mm top-left square, 20 mm L-shaped top-right and bottom-left marks, and 0.3 mm strokes. The required IDs are `regmark-tl`, `regmark-tr`, and `regmark-bl`. `inkscape-silhouette` derives registration offsets from these elements and skips layers whose labels contain `Print` or `Regmarks`.

The layout is intentionally conservative: all cut contours must fit in the rectangle inset by the full 20 mm registration arms. Preparation fails instead of silently resizing physical artwork or allowing a cut through a mark-exclusion area.

## Verify

```bash
uv run sticker-cut verify output/
```

Verification checks page pixels and DPI, SVG page units/viewBox, expected layers and registration IDs, cut count, closed contours, pairwise contour intersection, metadata bounding boxes, safe-area containment, coordinate scales, and artifact hashes. It writes `verify-report.json` and exits nonzero on disagreement. Intersecting or touching cut polygons set `cut_safety.regeneration_required` and must be resolved by regenerating or rearranging the source artwork before printing or cutting.

## Agent skill

The installable skill in [`skills/sticker-print-and-cut`](skills/sticker-print-and-cut/SKILL.md) teaches an agent to gather a sticker brief, generate isolated transparent artwork, enforce individual physical size, preview, verify, print, connect, and cut. Its current supported-cutter list contains only the physically verified Silhouette Cameo 5 Alpha, and it makes contour conflicts a hard regeneration gate.

## Exercise inkscape-silhouette without a cutter

```bash
uv run sticker-cut silhouette-dry-run output/cut-sheet.svg \
  --driver /path/to/inkscape-silhouette/sendto_silhouette.py
```

The wrapper performs two upstream dry runs. Current `inkscape-silhouette` still waits for a real optical-sensor response whenever registration is enabled, even with `--dry_run=True`. The first probe enables registration and search, confirms that the document marks are detected, captures the generated registration command, and treats the driver's specific no-sensor stop as expected. The second pass exercises complete blade-command generation with registration disabled but applies the exact same negative registration-origin offset that upstream applies after a successful scan. This covers the full hardware-free path without pretending that an optical scan occurred.

It captures:

```text
output/dry-run/
  status.json
  silhouette.log
  cutter-commands.bin
  registration-probe.log
  registration-commands.bin
  stdout.txt
  stderr.txt
```

The run passes only when the complete blade pass exits successfully, logs parsed cut paths, writes cutter commands, reaches ready status, and the registration probe detects the document marks and reaches either a real success or the expected no-hardware sensor stop. A cutter is neither required nor contacted. Use `--python` if the driver needs a different Python environment, or set `INKSCAPE_SILHOUETTE_DRIVER` instead of passing `--driver` every time.

## Opaque images

Fully opaque images fall back to foreground estimation based on color distance from the median border color. This is deliberately simple and reported in metadata. For reproducible contour extraction, remove the background first and use a transparent PNG.

## Tests

```bash
uv run pytest
```

The synthetic tests cover individual artwork and finished-size normalization, a known 40 mm object, a 2 mm border, multiple shapes, noise rejection, pairwise contour conflicts, page safety, output/coordinate agreement, registration SVG conventions, and dry-run capture.

`examples/synthetic-stickers.png` is a deterministic visual fixture containing a circle, rounded rectangle, concave star, irregular polygon, and a one-pixel noise artifact. Regenerate it with `uv run python examples/generate_fixture.py`.

The `examples/train-stickers/` directory contains the generated train source sheet and a complete blocked output set that demonstrates overlap detection and regeneration guidance.
