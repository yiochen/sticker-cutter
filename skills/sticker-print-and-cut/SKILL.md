---
name: sticker-print-and-cut
description: Create, size, verify, print, connect, and cut raster sticker sheets with the verified Silhouette Cameo 5 Alpha workflow. Use when the user wants to create, print, or cut stickers; connect to or troubleshoot “my cutter”; or cut supplied artwork with a Cameo 5 Alpha.
---

# Sticker Print and Cut

The preparation workflow requires [`uv`](https://docs.astral.sh/uv/); the bundled entrypoint resolves its own Python dependencies. If `uv` is unavailable, install it using the platform package manager or official installer. Hardware cutting additionally requires the external `inkscape-silhouette` driver described later.

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py --help
```

## Supported cutters

- **Silhouette Cameo 5 Alpha** — end-to-end verified with BLE discovery, optical registration, a carriage-1 AutoBlade, and Print & Cut.

This is currently the only cutter supported by this skill. The upstream driver lists other devices, but do not claim this workflow supports them until their connection, registration, coordinate behavior, and end positioning have been physically validated.

## Gather the sticker brief

Before generating artwork, confirm the decisions that affect generation or physical output:

- subject/theme and exact sticker count;
- visual style, palette, text, and whether variations should form a cohesive set;
- physical size and whether it means artwork size or finished bordered size;
- printed visual border, cut-border width, page/material, and kiss cut versus die cut;
- cutter model when connecting or cutting;
- where to store generated source artwork and intermediate/output files.

Do not re-ask details the user already supplied. For missing details, propose a compact default and ask whether they want changes. A useful starting proposal is: **8 stickers, cohesive colorful cartoon illustration, transparent background, 20 mm on each artwork's longest side, 2 mm cut border, 2 mm clearance between finished contours, Letter page**.

Ask once where the user wants the job files stored. Default to the current working directory and suggest a descriptive subdirectory such as `./plane-stickers/` to avoid mixing multiple jobs. Use that selected directory as `WORK` throughout the commands and tell the user the resolved path.

When a user says “2 cm each” without defining the measurement, propose **20 mm on the longest artwork side, aspect ratio preserved, cut border excluded**. Offer `finished` sizing if they mean the entire cut sticker must be 20 mm.

## Generate source artwork

Use an available image-generation capability for new artwork. Physical centimeters cannot be guaranteed by an image model; generate clean relative artwork first, then enforce physical size with the deterministic normalization script.

Construct the image prompt with these constraints:

- exact requested count in a loose grid, with generous empty space and no overlap;
- transparent background with no sheet, scene, texture, glow, drop shadow, or ambient objects;
- one complete, uncropped subject per sticker and one connected opaque silhouette per subject;
- no detached smoke, sparkles, labels, or tiny decorations unless the user explicitly wants them and accepts separate cut components;
- consistent rendering style, viewpoint, lighting, and edge treatment across the set;
- no text unless requested; when text matters, verify it visually;
- crisp alpha edges and no artwork touching the image boundary.

Show the raw generated image before resizing or contour processing. Check the count, subjects, transparency, connectedness, cropping, and obvious intersections. Regenerate immediately if the source already violates the brief.

## Enforce physical sticker size

Run `normalize` before generating cut contours when the user specifies a sticker size or wants uniform sizing. It detects each connected sticker, measures its foreground bounding contour, scales each component independently while preserving aspect ratio, and repacks the sheet with room for the fixed border and clearance.

For a 20 mm longest artwork side:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py normalize SOURCE.png \
  --output WORK/normalized.png \
  --sticker-size 20mm \
  --size-basis artwork \
  --border 2mm \
  --clearance 2mm \
  --page letter \
  --dpi 300
```

Use `--size-basis finished` when the requested size includes the cut border. With a 20 mm finished size and 2 mm border, the script scales artwork to a 16 mm longest side before contour offset. Read `normalized.normalization.json` and confirm every `output_artwork_mm.longest_side`, the detected count, and page fit. Never silently reduce requested size to fit more stickers.

If exact width and height are both important, clarify which dimension may vary; normalization currently preserves aspect ratio and enforces the longest side.

## Prepare and preview

Prefer transparent PNG input. Alpha gives deterministic component boundaries. A fully opaque image triggers heuristic foreground estimation from its border colors; report that fallback and prefer removing the background or regenerating with real transparency before a physical cut.

Generate fixed-width cut contours from the normalized sheet:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py prepare WORK/normalized.png \
  --output WORK/output \
  --input-dpi 300 \
  --dpi 300 \
  --border 2mm \
  --page letter
```

Read the JSON even when the command exits with status 2. Inspect `verify-report.json`, `metadata.json`, and `preview.png`. Show the visual preview and summarize sticker count, sizing, warnings, verification, and unsafe pairs. Proceed only when `verified` is true, `cut_safety.regeneration_required` is false, and every verification check passes.

Millimeters are canonical throughout the generated job. The same page geometry drives embedded artwork, registration marks, contours, print raster, preview, metadata, and artifact verification; never reposition one artifact independently. For the complete artifact contract, registration-mark convention, verification coverage, and dry-run diagnostics, read [references/workflow-artifacts.md](references/workflow-artifacts.md).

## Enforce contour safety

Contour conflicts are a hard stop. The script compares every pair of offset blade polygons and reports overlaps and edge touches. Magenta preview contours are involved in a conflict.

If `regeneration_required` is true or `nonintersecting-cut-contours` fails:

1. Do not print or cut the sheet.
2. Report the conflicting sticker IDs, relationship, and intersection area from `metadata.json`.
3. If the agent generated the source in this task, regenerate with stronger isolation/spacing constraints, normalize it again, and retry. Make at most two regeneration attempts after the first failure.
4. If the user supplied the source, ask before changing it.
5. After two failed regenerations, ask whether to change size, border, clearance, count, or layout. Never hide a conflict by deleting a contour.

Also stop for ambiguous DPI, unexpected component count, missing contours, registration-safe-area failures, or failed coordinate/hash checks. Fix the cause and rerun instead of bypassing verification.

Run verification explicitly after preparation and again immediately before a hardware cut:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py verify WORK/output
```

## Print, connect, and cut

Print `print-sheet.png`, never `preview.png`, at **100% / Actual Size** with all scaling disabled.

For installation on macOS, read [references/macos-install.md](references/macos-install.md). For connection, registration, recovery, or model-specific setup, read [references/silhouette-connections.md](references/silhouette-connections.md). Confirm model, operating system, and USB/Bluetooth transport; then run the hardware-free integration check:

```bash
uv run <skill-dir>/scripts/sticker_cut_cli.py silhouette-dry-run WORK/output/cut-sheet.svg \
  --driver /path/to/inkscape-silhouette/sendto_silhouette.py
```

A dry-run pass proves parsing and command generation, not physical communication or cut quality. Immediately before hardware cutting, rerun `verify`, confirm the exact SVG, cutter/model, material, mat, blade/tool, speed, force, passes, and kiss/die-cut intent. Do not guess material settings.

Use Inkscape's **Send to Silhouette** extension or its CLI only after the user authorizes that exact hardware run. Before BLE discovery or connection, ask the user to save and close Silhouette Studio, then confirm that neither Studio nor its Bluetooth helper still owns the cutter.

Start with a sacrificial test on the same material. If a production cut will follow on the same loaded mat, explicitly use `--endposition=start` for the test so the media returns to the job origin. Use `--endposition=below` only for the final job when presenting the sheet is desired.

Treat registration as physical state, not a retryable network call. After a registration timeout, abort, or unexpected head/media position:

1. Do not immediately rerun the full sheet.
2. Determine whether any contour commands or blade movement occurred; ask the user to inspect the sheet when uncertain.
3. Have the user manually unload, square, and reload the mat before retrying. Re-run `verify` and registration from the known loading origin.

The upstream driver exposes a low-level paper-feed helper but no verified, first-class mat-unload command. Do not use that helper as an automatic eject/release operation without a model-specific physical test and explicit authorization. Report driver success separately from the user's observed registration and cut quality.
