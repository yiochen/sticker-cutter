from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def as_dict(self) -> dict[str, float]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class PageSpec:
    name: str
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class RegistrationSpec:
    origin_x_mm: float
    origin_y_mm: float
    width_mm: float
    height_mm: float
    line_length_mm: float = 20.0
    square_size_mm: float = 5.0
    stroke_width_mm: float = 0.3

    @property
    def safe_rect(self) -> Rect:
        return Rect(
            self.origin_x_mm + self.line_length_mm,
            self.origin_y_mm + self.line_length_mm,
            self.origin_x_mm + self.width_mm - self.line_length_mm,
            self.origin_y_mm + self.height_mm - self.line_length_mm,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "style": "standard_three_point",
            "origin_mm": {"x": self.origin_x_mm, "y": self.origin_y_mm},
            "mark_to_mark_mm": {"x": self.width_mm, "y": self.height_mm},
            "line_length_mm": self.line_length_mm,
            "square_size_mm": self.square_size_mm,
            "stroke_width_mm": self.stroke_width_mm,
            "safe_rect_mm": self.safe_rect.as_dict(),
            "marks": {
                "top_left": {
                    "id": "regmark-tl",
                    "kind": "filled_square",
                    "x_mm": self.origin_x_mm,
                    "y_mm": self.origin_y_mm,
                },
                "top_right": {
                    "id": "regmark-tr",
                    "kind": "l_mark",
                    "x_mm": self.origin_x_mm + self.width_mm,
                    "y_mm": self.origin_y_mm,
                },
                "bottom_left": {
                    "id": "regmark-bl",
                    "kind": "l_mark",
                    "x_mm": self.origin_x_mm,
                    "y_mm": self.origin_y_mm + self.height_mm,
                },
            },
        }


@dataclass
class Sticker:
    id: str
    component_label: int
    mask_area_px: int
    artwork_bbox_px: tuple[int, int, int, int]
    artwork_bbox_mm: Rect
    cut_polygon: Polygon


@dataclass(frozen=True)
class ContourConflict:
    sticker_ids: tuple[str, str]
    relationship: str
    intersection_area_mm2: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "sticker_ids": list(self.sticker_ids),
            "relationship": self.relationship,
            "intersection_area_mm2": self.intersection_area_mm2,
        }


@dataclass
class Layout:
    input_path: Path
    input_width_px: int
    input_height_px: int
    input_dpi: float
    output_dpi: float
    page: PageSpec
    registration: RegistrationSpec
    artwork_rect_mm: Rect
    border_mm: float
    stickers: list[Sticker]
    mask_source: str
    contour_conflicts: list[ContourConflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def input_mm_per_px(self) -> float:
        return 25.4 / self.input_dpi
