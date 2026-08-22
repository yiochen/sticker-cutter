from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .geometry import PreparationError, extract_foreground_mask
from .model import PageSpec, RegistrationSpec


@dataclass(frozen=True)
class NormalizedSticker:
    id: str
    source_bbox_px: tuple[int, int, int, int]
    source_area_px: int
    output_bbox_px: tuple[int, int, int, int]
    scale: float

    def as_dict(self, dpi: float) -> dict[str, Any]:
        x, y, width, height = self.output_bbox_px
        mm_per_px = 25.4 / dpi
        return {
            "id": self.id,
            "source_bbox_px": {
                "x": self.source_bbox_px[0],
                "y": self.source_bbox_px[1],
                "width": self.source_bbox_px[2],
                "height": self.source_bbox_px[3],
            },
            "source_area_px": self.source_area_px,
            "scale": self.scale,
            "output_bbox_px": {"x": x, "y": y, "width": width, "height": height},
            "output_artwork_mm": {
                "width": width * mm_per_px,
                "height": height * mm_per_px,
                "longest_side": max(width, height) * mm_per_px,
            },
        }


@dataclass(frozen=True)
class NormalizationResult:
    output_path: Path
    metadata_path: Path
    sticker_size_mm: float
    size_basis: str
    artwork_size_mm: float
    output_dpi: float
    border_mm: float
    clearance_mm: float
    closing_mm: float
    page: PageSpec
    columns: int
    rows: int
    stickers: list[NormalizedSticker]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "output": self.output_path.name,
            "metadata": self.metadata_path.name,
            "sticker_count": len(self.stickers),
            "requested_sticker_size_mm": self.sticker_size_mm,
            "size_basis": self.size_basis,
            "target_artwork_longest_side_mm": self.artwork_size_mm,
            "estimated_finished_longest_side_mm": self.artwork_size_mm + 2 * self.border_mm,
            "dpi": self.output_dpi,
            "border_mm": self.border_mm,
            "clearance_mm": self.clearance_mm,
            "closing_mm": self.closing_mm,
            "page": {
                "name": self.page.name,
                "width_mm": self.page.width_mm,
                "height_mm": self.page.height_mm,
            },
            "packing": {"columns": self.columns, "rows": self.rows},
            "warnings": self.warnings,
            "stickers": [sticker.as_dict(self.output_dpi) for sticker in self.stickers],
        }


def _best_grid(
    count: int,
    *,
    cell_px: int,
    gap_px: int,
    padding_px: int,
    max_width_px: int,
    max_height_px: int,
) -> tuple[int, int, int, int]:
    candidates: list[tuple[float, int, int, int, int, int]] = []
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        width = 2 * padding_px + columns * cell_px + (columns - 1) * gap_px
        height = 2 * padding_px + rows * cell_px + (rows - 1) * gap_px
        if width <= max_width_px and height <= max_height_px:
            utilization = max(width / max_width_px, height / max_height_px)
            candidates.append((utilization, width * height, columns, rows, width, height))
    if not candidates:
        raise PreparationError(
            f"{count} sticker(s) at the requested size do not fit in the registration-safe page area. "
            "Choose a smaller sticker size, less clearance, a larger page, or fewer stickers."
        )
    _, _, columns, rows, width, height = min(candidates)
    return columns, rows, width, height


def normalize_sticker_sheet(
    input_path: Path,
    output_path: Path,
    *,
    sticker_size_mm: float,
    size_basis: str,
    page: PageSpec,
    output_dpi: float = 300.0,
    border_mm: float = 2.0,
    clearance_mm: float = 2.0,
    closing_mm: float = 0.3,
    alpha_threshold: int = 16,
    background_threshold: float = 24.0,
    min_area_px: int = 16,
    reg_origin_mm: float = 10.0,
) -> NormalizationResult:
    if sticker_size_mm <= 0 or output_dpi <= 0:
        raise PreparationError("Sticker size and output DPI must be positive")
    if border_mm < 0 or clearance_mm < 0 or closing_mm < 0 or min_area_px < 0:
        raise PreparationError("Border, clearance, closing, and minimum area must be non-negative")
    if size_basis not in {"artwork", "finished"}:
        raise PreparationError("Size basis must be 'artwork' or 'finished'")

    artwork_size_mm = sticker_size_mm if size_basis == "artwork" else sticker_size_mm - 2 * border_mm
    if artwork_size_mm <= 0:
        raise PreparationError(
            f"A finished size of {sticker_size_mm:g} mm must be greater than twice the {border_mm:g} mm border"
        )

    image = Image.open(input_path).convert("RGBA")
    rgba = np.asarray(image).copy()
    mask, mask_source, warnings = extract_foreground_mask(image, alpha_threshold, background_threshold)
    source_px_per_mm = output_dpi / 25.4
    closing_px = max(1, int(round(closing_mm * source_px_per_mm)))
    if closing_px > 1:
        kernel_size = closing_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components: list[tuple[int, int, int, int, int, int]] = []
    ignored = 0
    for label in range(1, count):
        x, y, width, height, area = [int(value) for value in stats[label]]
        if area < min_area_px or width < 2 or height < 2:
            ignored += 1
            continue
        components.append((label, x, y, width, height, area))
    if ignored:
        warnings.append(f"Ignored {ignored} component(s) below {min_area_px} source pixels or too small to resize.")
    if not components:
        raise PreparationError("No sticker-sized foreground components were detected")

    px_per_mm = output_dpi / 25.4
    target_px = max(1, int(round(artwork_size_mm * px_per_mm)))
    gap_px = max(0, int(math.ceil((2 * border_mm + clearance_mm) * px_per_mm)))
    padding_px = max(1, int(math.ceil(border_mm * px_per_mm)) + 1)
    registration = RegistrationSpec(
        reg_origin_mm,
        reg_origin_mm,
        page.width_mm - 2 * reg_origin_mm,
        page.height_mm - 2 * reg_origin_mm,
    )
    safe = registration.safe_rect
    columns, rows, canvas_width, canvas_height = _best_grid(
        len(components),
        cell_px=target_px,
        gap_px=gap_px,
        padding_px=padding_px,
        max_width_px=int(math.floor(safe.width * px_per_mm)),
        max_height_px=int(math.floor(safe.height * px_per_mm)),
    )

    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    normalized: list[NormalizedSticker] = []
    for index, (label, x, y, width, height, area) in enumerate(components):
        component_rgba = rgba[y : y + height, x : x + width].copy()
        component_mask = labels[y : y + height, x : x + width] == label
        component_rgba[:, :, 3] = np.where(component_mask, component_rgba[:, :, 3], 0)
        component_image = Image.fromarray(component_rgba)
        scale = target_px / max(width, height)
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        resized = component_image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)

        row, column = divmod(index, columns)
        cell_x = padding_px + column * (target_px + gap_px)
        cell_y = padding_px + row * (target_px + gap_px)
        output_x = cell_x + (target_px - resized_width) // 2
        output_y = cell_y + (target_px - resized_height) // 2
        canvas.alpha_composite(resized, (output_x, output_y))
        normalized.append(
            NormalizedSticker(
                id=f"sticker-{index + 1:03d}",
                source_bbox_px=(x, y, width, height),
                source_area_px=area,
                output_bbox_px=(output_x, output_y, resized_width, resized_height),
                scale=scale,
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, dpi=(output_dpi, output_dpi), optimize=True)
    metadata_path = output_path.with_suffix(".normalization.json")
    result = NormalizationResult(
        output_path=output_path,
        metadata_path=metadata_path,
        sticker_size_mm=sticker_size_mm,
        size_basis=size_basis,
        artwork_size_mm=artwork_size_mm,
        output_dpi=output_dpi,
        border_mm=border_mm,
        clearance_mm=clearance_mm,
        closing_mm=closing_mm,
        page=page,
        columns=columns,
        rows=rows,
        stickers=normalized,
        warnings=[f"Foreground detection used {mask_source}.", *warnings],
    )
    metadata_path.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
    return result
