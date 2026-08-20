from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from .model import Layout, PageSpec, Rect, RegistrationSpec, Sticker


PAGE_SIZES = {
    "letter": PageSpec("letter", 215.9, 279.4),
    "a4": PageSpec("a4", 210.0, 297.0),
}


class PreparationError(ValueError):
    pass


def parse_mm(value: str | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in)?\s*", value.lower())
    if not match:
        raise ValueError(f"Invalid physical length: {value!r}")
    amount = float(match.group(1))
    unit = match.group(2) or "mm"
    return amount * {"mm": 1.0, "cm": 10.0, "in": 25.4}[unit]


def page_spec(value: str) -> PageSpec:
    normalized = value.lower()
    if normalized in PAGE_SIZES:
        return PAGE_SIZES[normalized]
    match = re.fullmatch(r"\s*([0-9.]+)\s*(?:mm)?\s*[x×]\s*([0-9.]+)\s*(?:mm)?\s*", normalized)
    if not match:
        raise ValueError("Page must be 'letter', 'a4', or WIDTHxHEIGHT in mm")
    width, height = map(float, match.groups())
    if width <= 0 or height <= 0:
        raise ValueError("Page dimensions must be positive")
    return PageSpec("custom", width, height)


def resolve_input_dpi(image: Image.Image, requested_dpi: float | None) -> tuple[float, list[str]]:
    if requested_dpi is not None:
        if requested_dpi <= 0:
            raise PreparationError("Input DPI must be positive")
        return requested_dpi, []
    embedded = image.info.get("dpi")
    if embedded:
        values = embedded if isinstance(embedded, tuple) else (embedded, embedded)
        usable = [float(v) for v in values[:2] if float(v) > 0]
        if usable and max(usable) - min(usable) < 1.0:
            return sum(usable) / len(usable), []
    return 300.0, ["Input has no reliable DPI metadata; assumed 300 DPI. Use --input-dpi to override."]


def extract_foreground_mask(
    image: Image.Image,
    alpha_threshold: int,
    background_threshold: float,
) -> tuple[np.ndarray, str, list[str]]:
    rgba = np.asarray(image.convert("RGBA"))
    alpha = rgba[:, :, 3]
    if alpha.min() < alpha_threshold and np.any(alpha >= alpha_threshold):
        return (alpha >= alpha_threshold).astype(np.uint8), "alpha", []

    rgb = rgba[:, :, :3].astype(np.float32)
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    background = np.median(border, axis=0)
    distance = np.linalg.norm(rgb - background, axis=2)
    warning = (
        "Input is fully opaque; foreground was estimated from border-color distance. "
        "Transparent PNG input is more reliable."
    )
    return (distance >= background_threshold).astype(np.uint8), "border_color", [warning]


def _largest_polygon(geometry: BaseGeometry) -> Polygon:
    if geometry.is_empty:
        raise PreparationError("Contour became empty during smoothing/offset")
    if geometry.geom_type == "Polygon":
        return geometry  # type: ignore[return-value]
    polygons = [part for part in getattr(geometry, "geoms", []) if part.geom_type == "Polygon"]
    if not polygons:
        raise PreparationError(f"Expected polygon geometry, got {geometry.geom_type}")
    return max(polygons, key=lambda polygon: polygon.area)


def build_layout(
    input_path: Path,
    *,
    page: PageSpec,
    border_mm: float = 2.0,
    input_dpi: float | None = None,
    output_dpi: float = 300.0,
    alpha_threshold: int = 16,
    background_threshold: float = 24.0,
    min_area_mm2: float = 1.0,
    closing_mm: float = 0.3,
    simplify_mm: float = 0.12,
    reg_origin_mm: float = 10.0,
) -> Layout:
    if border_mm < 0 or output_dpi <= 0 or min_area_mm2 < 0:
        raise PreparationError("Border, output DPI, and minimum area must be non-negative (DPI must be positive)")
    image = Image.open(input_path)
    resolved_dpi, warnings = resolve_input_dpi(image, input_dpi)
    mm_per_px = 25.4 / resolved_dpi
    mask, mask_source, mask_warnings = extract_foreground_mask(image, alpha_threshold, background_threshold)
    warnings.extend(mask_warnings)

    closing_px = max(1, int(round(closing_mm / mm_per_px)))
    if closing_px > 1:
        kernel_size = closing_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    registration = RegistrationSpec(
        reg_origin_mm,
        reg_origin_mm,
        page.width_mm - 2 * reg_origin_mm,
        page.height_mm - 2 * reg_origin_mm,
    )
    safe = registration.safe_rect
    if safe.width <= 0 or safe.height <= 0:
        raise PreparationError("Page is too small for the configured registration marks")

    input_width_px, input_height_px = image.size
    artwork_width_mm = input_width_px * mm_per_px
    artwork_height_mm = input_height_px * mm_per_px
    artwork_rect = Rect(
        safe.left + (safe.width - artwork_width_mm) / 2,
        safe.top + (safe.height - artwork_height_mm) / 2,
        safe.left + (safe.width + artwork_width_mm) / 2,
        safe.top + (safe.height + artwork_height_mm) / 2,
    )
    if artwork_rect.left < safe.left or artwork_rect.top < safe.top or artwork_rect.right > safe.right or artwork_rect.bottom > safe.bottom:
        raise PreparationError(
            f"Input is {artwork_width_mm:.2f} x {artwork_height_mm:.2f} mm at {resolved_dpi:g} DPI, "
            f"but the conservative registration-safe area is only {safe.width:.2f} x {safe.height:.2f} mm. "
            "Increase --input-dpi, choose a larger page, or resize the source intentionally."
        )

    safe_polygon = box(safe.left, safe.top, safe.right, safe.bottom)
    stickers: list[Sticker] = []
    ignored = 0
    min_area_px = min_area_mm2 / (mm_per_px * mm_per_px)
    for label in range(1, count):
        x, y, width, height, area = [int(value) for value in stats[label]]
        if area < min_area_px:
            ignored += 1
            continue
        component = (labels == label).astype(np.uint8)
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea).reshape(-1, 2)
        if len(contour) < 3:
            ignored += 1
            continue
        page_points = [
            (
                artwork_rect.left + (float(px) + 0.5) * mm_per_px,
                artwork_rect.top + (float(py) + 0.5) * mm_per_px,
            )
            for px, py in contour
        ]
        polygon = Polygon(page_points)
        if not polygon.is_valid:
            polygon = _largest_polygon(polygon.buffer(0))
        # A half-pixel buffer converts OpenCV's pixel-center contour into an
        # approximation of the outer mask boundary before applying the physical border.
        polygon = _largest_polygon(polygon.buffer(mm_per_px / 2, join_style="round"))
        if simplify_mm:
            polygon = _largest_polygon(polygon.simplify(simplify_mm, preserve_topology=True))
        cut_polygon = _largest_polygon(polygon.buffer(border_mm, quad_segs=8, join_style="round"))
        if simplify_mm:
            cut_polygon = _largest_polygon(cut_polygon.simplify(simplify_mm / 2, preserve_topology=True))
        if not safe_polygon.covers(cut_polygon):
            bounds = cut_polygon.bounds
            raise PreparationError(
                f"Sticker component {label} cut contour {tuple(round(v, 2) for v in bounds)} mm "
                f"overlaps the registration exclusion area {safe.as_dict()}."
            )

        artwork_bbox_mm = Rect(
            artwork_rect.left + x * mm_per_px,
            artwork_rect.top + y * mm_per_px,
            artwork_rect.left + (x + width) * mm_per_px,
            artwork_rect.top + (y + height) * mm_per_px,
        )
        stickers.append(
            Sticker(
                id=f"sticker-{len(stickers) + 1:03d}",
                component_label=label,
                mask_area_px=area,
                artwork_bbox_px=(x, y, width, height),
                artwork_bbox_mm=artwork_bbox_mm,
                cut_polygon=cut_polygon,
            )
        )

    if ignored:
        warnings.append(f"Ignored {ignored} foreground component(s) below {min_area_mm2:g} mm² or without a usable contour.")
    if not stickers:
        raise PreparationError("No sticker-sized foreground components were detected")

    return Layout(
        input_path=input_path,
        input_width_px=input_width_px,
        input_height_px=input_height_px,
        input_dpi=resolved_dpi,
        output_dpi=output_dpi,
        page=page,
        registration=registration,
        artwork_rect_mm=artwork_rect,
        border_mm=border_mm,
        stickers=stickers,
        mask_source=mask_source,
        warnings=warnings,
    )
