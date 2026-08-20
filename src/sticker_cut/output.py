from __future__ import annotations

import base64
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from .model import Layout, Rect, RegistrationSpec, Sticker


SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"

ET.register_namespace("", SVG_NS)
ET.register_namespace("inkscape", INKSCAPE_NS)
ET.register_namespace("sodipodi", SODIPODI_NS)


def _mm_to_px(mm: float, dpi: float) -> int:
    return int(round(mm * dpi / 25.4))


def _round(value: float) -> float:
    return round(value, 5)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _draw_regmarks(draw: ImageDraw.ImageDraw, reg: RegistrationSpec, dpi: float) -> None:
    def point(x_mm: float, y_mm: float) -> tuple[int, int]:
        return _mm_to_px(x_mm, dpi), _mm_to_px(y_mm, dpi)

    line_px = max(1, _mm_to_px(reg.stroke_width_mm, dpi))
    x0, y0 = point(reg.origin_x_mm, reg.origin_y_mm)
    size = _mm_to_px(reg.square_size_mm, dpi)
    draw.rectangle((x0, y0, x0 + size, y0 + size), fill="black")

    right = reg.origin_x_mm + reg.width_mm
    bottom = reg.origin_y_mm + reg.height_mm
    draw.line(
        [point(right - reg.line_length_mm, reg.origin_y_mm), point(right, reg.origin_y_mm), point(right, reg.origin_y_mm + reg.line_length_mm)],
        fill="black",
        width=line_px,
        joint="curve",
    )
    draw.line(
        [point(reg.origin_x_mm + reg.line_length_mm, bottom), point(reg.origin_x_mm, bottom), point(reg.origin_x_mm, bottom - reg.line_length_mm)],
        fill="black",
        width=line_px,
        joint="curve",
    )


def render_print_sheet(layout: Layout, output_path: Path) -> Image.Image:
    width_px = _mm_to_px(layout.page.width_mm, layout.output_dpi)
    height_px = _mm_to_px(layout.page.height_mm, layout.output_dpi)
    page = Image.new("RGBA", (width_px, height_px), "white")
    artwork = Image.open(layout.input_path).convert("RGBA")
    target_size = (
        _mm_to_px(layout.artwork_rect_mm.width, layout.output_dpi),
        _mm_to_px(layout.artwork_rect_mm.height, layout.output_dpi),
    )
    if artwork.size != target_size:
        artwork = artwork.resize(target_size, Image.Resampling.LANCZOS)
    page.alpha_composite(
        artwork,
        (_mm_to_px(layout.artwork_rect_mm.left, layout.output_dpi), _mm_to_px(layout.artwork_rect_mm.top, layout.output_dpi)),
    )
    _draw_regmarks(ImageDraw.Draw(page), layout.registration, layout.output_dpi)
    rgb = page.convert("RGB")
    rgb.save(output_path, dpi=(layout.output_dpi, layout.output_dpi), optimize=True)
    return rgb


def _path_data(sticker: Sticker) -> str:
    points = list(sticker.cut_polygon.exterior.coords)
    if points and points[0] == points[-1]:
        points = points[:-1]
    commands = [f"M {_round(points[0][0])},{_round(points[0][1])}"]
    commands.extend(f"L {_round(x)},{_round(y)}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def _image_data_uri(path: Path) -> str:
    image = Image.open(path).convert("RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _layer(root: ET.Element, layer_id: str, label: str, **attributes: str) -> ET.Element:
    return ET.SubElement(
        root,
        f"{{{SVG_NS}}}g",
        {
            "id": layer_id,
            f"{{{INKSCAPE_NS}}}groupmode": "layer",
            f"{{{INKSCAPE_NS}}}label": label,
            **attributes,
        },
    )


def write_cut_svg(layout: Layout, output_path: Path) -> None:
    image_uri = _image_data_uri(layout.input_path)
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{layout.page.width_mm:g}mm",
            "height": f"{layout.page.height_mm:g}mm",
            "viewBox": f"0 0 {layout.page.width_mm:g} {layout.page.height_mm:g}",
            "version": "1.1",
            f"{{{SODIPODI_NS}}}docname": output_path.name,
            "data-canonical-units": "mm",
        },
    )
    ET.SubElement(
        root,
        f"{{{SODIPODI_NS}}}namedview",
        {"id": "namedview", f"{{{INKSCAPE_NS}}}document-units": "mm", "pagecolor": "#ffffff"},
    )
    print_layer = _layer(root, "print", "Print")
    ET.SubElement(
        print_layer,
        f"{{{SVG_NS}}}image",
        {
            "id": "sticker-artwork",
            "x": str(_round(layout.artwork_rect_mm.left)),
            "y": str(_round(layout.artwork_rect_mm.top)),
            "width": str(_round(layout.artwork_rect_mm.width)),
            "height": str(_round(layout.artwork_rect_mm.height)),
            "preserveAspectRatio": "none",
            "href": image_uri,
        },
    )

    reg = layout.registration
    reg_layer = _layer(
        root,
        "regmark",
        "Regmarks",
        **{
            f"{{{SODIPODI_NS}}}insensitive": "true",
            "data-origin-x-mm": str(reg.origin_x_mm),
            "data-origin-y-mm": str(reg.origin_y_mm),
            "data-width-mm": str(reg.width_mm),
            "data-height-mm": str(reg.height_mm),
        },
    )
    ET.SubElement(
        reg_layer,
        f"{{{SVG_NS}}}rect",
        {
            "id": "regmark-safe-area",
            "x": str(_round(reg.safe_rect.left)),
            "y": str(_round(reg.safe_rect.top)),
            "width": str(_round(reg.safe_rect.width)),
            "height": str(_round(reg.safe_rect.height)),
            "style": "fill:none;stroke:none",
            "data-role": "conservative-registration-safe-area",
        },
    )
    ET.SubElement(
        reg_layer,
        f"{{{SVG_NS}}}rect",
        {
            "id": "regmark-tl",
            f"{{{INKSCAPE_NS}}}label": "regmark-tl",
            "x": str(reg.origin_x_mm),
            "y": str(reg.origin_y_mm),
            "width": str(reg.square_size_mm),
            "height": str(reg.square_size_mm),
            "style": "fill:#000000;stroke:none",
        },
    )
    right = reg.origin_x_mm + reg.width_mm
    bottom = reg.origin_y_mm + reg.height_mm
    ET.SubElement(
        reg_layer,
        f"{{{SVG_NS}}}path",
        {
            "id": "regmark-tr",
            f"{{{INKSCAPE_NS}}}label": "regmark-tr",
            "d": f"M {_round(right - reg.line_length_mm)},{_round(reg.origin_y_mm)} L {_round(right)},{_round(reg.origin_y_mm)} L {_round(right)},{_round(reg.origin_y_mm + reg.line_length_mm)}",
            "style": f"fill:none;stroke:#000000;stroke-width:{reg.stroke_width_mm};stroke-linecap:square;stroke-linejoin:miter",
        },
    )
    ET.SubElement(
        reg_layer,
        f"{{{SVG_NS}}}path",
        {
            "id": "regmark-bl",
            f"{{{INKSCAPE_NS}}}label": "regmark-bl",
            "d": f"M {_round(reg.origin_x_mm + reg.line_length_mm)},{_round(bottom)} L {_round(reg.origin_x_mm)},{_round(bottom)} L {_round(reg.origin_x_mm)},{_round(bottom - reg.line_length_mm)}",
            "style": f"fill:none;stroke:#000000;stroke-width:{reg.stroke_width_mm};stroke-linecap:square;stroke-linejoin:miter",
        },
    )
    note = ET.SubElement(
        reg_layer,
        f"{{{SVG_NS}}}text",
        {
            "id": "regmark-notes",
            "x": str(reg.safe_rect.left),
            "y": str(layout.page.height_mm - 2),
            "style": "font-size:2.5px;fill:#555555",
        },
    )
    note.text = (
        f"mark distance from document: Left={reg.origin_x_mm}mm, Top={reg.origin_y_mm}mm; "
        f"mark to mark distance: X={reg.width_mm}mm, Y={reg.height_mm}mm;"
    )

    cut_layer = _layer(root, "cut", "Cut", style="display:inline")
    for sticker in layout.stickers:
        ET.SubElement(
            cut_layer,
            f"{{{SVG_NS}}}path",
            {
                "id": f"cut-{sticker.id}",
                "d": _path_data(sticker),
                "style": "fill:none;stroke:#ff0000;stroke-width:0.2;stroke-linejoin:round",
                "data-sticker-id": sticker.id,
            },
        )

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)


def write_preview(layout: Layout, print_sheet: Image.Image, output_path: Path) -> None:
    preview = print_sheet.convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    dpi = layout.output_dpi
    safe = layout.registration.safe_rect
    draw.rectangle(
        (_mm_to_px(safe.left, dpi), _mm_to_px(safe.top, dpi), _mm_to_px(safe.right, dpi), _mm_to_px(safe.bottom, dpi)),
        outline=(0, 160, 220, 210),
        width=max(2, _mm_to_px(0.35, dpi)),
    )
    for sticker in layout.stickers:
        points = [(_mm_to_px(x, dpi), _mm_to_px(y, dpi)) for x, y in sticker.cut_polygon.exterior.coords]
        draw.line(points, fill=(255, 0, 30, 235), width=max(3, _mm_to_px(0.4, dpi)), joint="curve")
    preview = Image.alpha_composite(preview, overlay).convert("RGB")
    preview.save(output_path, dpi=(dpi, dpi), optimize=True)


def _rect_from_bounds(bounds: tuple[float, float, float, float]) -> Rect:
    return Rect(bounds[0], bounds[1], bounds[2], bounds[3])


def metadata_dict(layout: Layout, outputs: dict[str, Path]) -> dict:
    input_to_page = [
        [layout.input_mm_per_px, 0.0, layout.artwork_rect_mm.left],
        [0.0, layout.input_mm_per_px, layout.artwork_rect_mm.top],
        [0.0, 0.0, 1.0],
    ]
    page_to_print = [
        [layout.output_dpi / 25.4, 0.0, 0.0],
        [0.0, layout.output_dpi / 25.4, 0.0],
        [0.0, 0.0, 1.0],
    ]
    stickers = []
    for sticker in layout.stickers:
        points = [[_round(x), _round(y)] for x, y in sticker.cut_polygon.exterior.coords]
        stickers.append(
            {
                "id": sticker.id,
                "component_label": sticker.component_label,
                "mask_area_px": sticker.mask_area_px,
                "artwork_bbox_px": {
                    "x": sticker.artwork_bbox_px[0],
                    "y": sticker.artwork_bbox_px[1],
                    "width": sticker.artwork_bbox_px[2],
                    "height": sticker.artwork_bbox_px[3],
                },
                "artwork_bbox_mm": {key: _round(value) for key, value in sticker.artwork_bbox_mm.as_dict().items()},
                "cut_bbox_mm": {key: _round(value) for key, value in _rect_from_bounds(sticker.cut_polygon.bounds).as_dict().items()},
                "cut_area_mm2": _round(sticker.cut_polygon.area),
                "cut_perimeter_mm": _round(sticker.cut_polygon.length),
                "contour_vertex_count": len(points) - 1,
                "cut_contour_mm": points,
            }
        )
    return {
        "schema_version": 1,
        "canonical_units": "mm",
        "page": {"name": layout.page.name, "width_mm": layout.page.width_mm, "height_mm": layout.page.height_mm},
        "input": {
            "file": str(layout.input_path.resolve()),
            "sha256": _sha256(layout.input_path),
            "width_px": layout.input_width_px,
            "height_px": layout.input_height_px,
            "dpi": layout.input_dpi,
            "mask_source": layout.mask_source,
        },
        "render": {
            "dpi": layout.output_dpi,
            "page_width_px": _mm_to_px(layout.page.width_mm, layout.output_dpi),
            "page_height_px": _mm_to_px(layout.page.height_mm, layout.output_dpi),
            "rounding": "nearest_integer_pixel",
        },
        "artwork_rect_mm": {key: _round(value) for key, value in layout.artwork_rect_mm.as_dict().items()},
        "artwork_rect_print_px": {
            "x": _mm_to_px(layout.artwork_rect_mm.left, layout.output_dpi),
            "y": _mm_to_px(layout.artwork_rect_mm.top, layout.output_dpi),
            "width": _mm_to_px(layout.artwork_rect_mm.width, layout.output_dpi),
            "height": _mm_to_px(layout.artwork_rect_mm.height, layout.output_dpi),
        },
        "border_mm": layout.border_mm,
        "sticker_count": len(layout.stickers),
        "stickers": stickers,
        "registration": layout.registration.as_dict(),
        "coordinate_transforms": {
            "input_pixels_to_page_mm": input_to_page,
            "page_mm_to_print_pixels": page_to_print,
            "cut_paths": "SVG viewBox coordinates are millimeters and use the page origin directly.",
            "registration_marks": "SVG viewBox coordinates are millimeters and use the page origin directly.",
        },
        "warnings": layout.warnings,
        "outputs": {
            name: {"file": path.name, "sha256": _sha256(path)} for name, path in outputs.items()
        },
    }


def write_outputs(layout: Layout, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    print_path = output_dir / "print-sheet.png"
    svg_path = output_dir / "cut-sheet.svg"
    preview_path = output_dir / "preview.png"
    metadata_path = output_dir / "metadata.json"

    print_sheet = render_print_sheet(layout, print_path)
    write_cut_svg(layout, svg_path)
    write_preview(layout, print_sheet, preview_path)
    artifacts = {"print_sheet": print_path, "cut_sheet": svg_path, "preview": preview_path}
    metadata_path.write_text(json.dumps(metadata_dict(layout, artifacts), indent=2) + "\n", encoding="utf-8")

    dry_run_dir = output_dir / "dry-run"
    dry_run_dir.mkdir(exist_ok=True)
    instructions = {
        "status": "not_run",
        "message": "Run `sticker-cut silhouette-dry-run OUTPUT/cut-sheet.svg` to exercise inkscape-silhouette without a cutter.",
    }
    (dry_run_dir / "status.json").write_text(json.dumps(instructions, indent=2) + "\n", encoding="utf-8")
    return {**artifacts, "metadata": metadata_path}
