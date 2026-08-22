from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image
from shapely.geometry import Polygon


SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _number(value: str) -> float:
    match = re.fullmatch(r"\s*([-+0-9.eE]+)(?:mm)?\s*", value)
    if not match:
        raise ValueError(f"Cannot parse physical value {value!r}")
    return float(match.group(1))


def _path_points(path_data: str) -> list[tuple[float, float]]:
    numbers = [
        float(value)
        for value in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", path_data)
    ]
    return list(zip(numbers[0::2], numbers[1::2]))


def verify_output(output_dir: Path) -> dict:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    metadata_path = output_dir / "metadata.json"
    print_path = output_dir / "print-sheet.png"
    svg_path = output_dir / "cut-sheet.svg"
    preview_path = output_dir / "preview.png"
    for path in (metadata_path, print_path, svg_path, preview_path):
        check(f"file:{path.name}", path.is_file(), "present" if path.is_file() else "missing")
    if not all(path.is_file() for path in (metadata_path, print_path, svg_path, preview_path)):
        return {"passed": False, "checks": checks}

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    page = metadata["page"]
    render = metadata["render"]
    stickers = metadata["stickers"]
    safe = metadata["registration"]["safe_rect_mm"]

    with Image.open(print_path) as image:
        check(
            "print-raster-size",
            image.size == (render["page_width_px"], render["page_height_px"]),
            f"actual={image.size}, expected={(render['page_width_px'], render['page_height_px'])}",
        )
        dpi = image.info.get("dpi", (0, 0))
        check(
            "print-dpi",
            bool(dpi) and all(abs(float(value) - render["dpi"]) < 0.1 for value in dpi[:2]),
            f"actual={dpi}, expected={render['dpi']}",
        )

    root = ET.parse(svg_path).getroot()
    svg_size = (_number(root.get("width", "0")), _number(root.get("height", "0")))
    check(
        "svg-physical-page-size",
        abs(svg_size[0] - page["width_mm"]) < 1e-6 and abs(svg_size[1] - page["height_mm"]) < 1e-6,
        f"actual={svg_size} mm, expected={(page['width_mm'], page['height_mm'])} mm",
    )
    viewbox = [float(value) for value in root.get("viewBox", "").split()]
    check(
        "svg-mm-viewbox",
        viewbox == [0.0, 0.0, float(page["width_mm"]), float(page["height_mm"])],
        f"viewBox={viewbox}",
    )

    layers = {
        node.get(f"{{{INKSCAPE_NS}}}label"): node
        for node in root.findall(f".//{{{SVG_NS}}}g")
        if node.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
    }
    check("svg-layers", {"Print", "Cut", "Regmarks"}.issubset(layers), f"layers={sorted(key for key in layers if key)}")
    elements_by_id = {node.get("id"): node for node in root.iter() if node.get("id")}
    required_marks = {"regmark-tl", "regmark-tr", "regmark-bl"}
    check("registration-element-ids", required_marks.issubset(elements_by_id), f"found={sorted(required_marks & elements_by_id.keys())}")
    cut_paths = [node for node in layers.get("Cut", []) if node.tag == f"{{{SVG_NS}}}path"]
    check(
        "cut-path-count",
        len(cut_paths) == metadata["sticker_count"] == len(stickers),
        f"svg={len(cut_paths)}, metadata={metadata['sticker_count']}",
    )

    artwork_image = elements_by_id.get("sticker-artwork")
    artwork_mm = metadata["artwork_rect_mm"]
    artwork_svg_agrees = artwork_image is not None and all(
        abs(float(artwork_image.get(attribute, "nan")) - artwork_mm[key]) < 1e-5
        for attribute, key in (("x", "left"), ("y", "top"), ("width", "width"), ("height", "height"))
    )
    check("svg-artwork-placement", artwork_svg_agrees, f"artwork_rect_mm={artwork_mm}")

    rounded_artwork = metadata["artwork_rect_print_px"]
    calculated_artwork = {
        "x": round(artwork_mm["left"] * render["dpi"] / 25.4),
        "y": round(artwork_mm["top"] * render["dpi"] / 25.4),
        "width": round(artwork_mm["width"] * render["dpi"] / 25.4),
        "height": round(artwork_mm["height"] * render["dpi"] / 25.4),
    }
    check(
        "print-artwork-placement-transform",
        all(abs(rounded_artwork[key] - calculated_artwork[key]) <= 1 for key in calculated_artwork),
        f"recorded={rounded_artwork}, calculated={calculated_artwork}",
    )

    reg_layer = elements_by_id.get("regmark")
    registration = metadata["registration"]
    origin = registration["origin_mm"]
    spacing = registration["mark_to_mark_mm"]
    reg_layer_agrees = reg_layer is not None and all(
        abs(float(reg_layer.get(attribute, "nan")) - expected) < 1e-6
        for attribute, expected in (
            ("data-origin-x-mm", origin["x"]),
            ("data-origin-y-mm", origin["y"]),
            ("data-width-mm", spacing["x"]),
            ("data-height-mm", spacing["y"]),
        )
    )
    top_left = elements_by_id.get("regmark-tl")
    top_left_agrees = top_left is not None and all(
        abs(float(top_left.get(attribute, "nan")) - expected) < 1e-6
        for attribute, expected in (
            ("x", origin["x"]),
            ("y", origin["y"]),
            ("width", registration["square_size_mm"]),
            ("height", registration["square_size_mm"]),
        )
    )
    right_points = _path_points(elements_by_id["regmark-tr"].get("d", "")) if "regmark-tr" in elements_by_id else []
    bottom_points = _path_points(elements_by_id["regmark-bl"].get("d", "")) if "regmark-bl" in elements_by_id else []
    expected_right = origin["x"] + spacing["x"]
    expected_bottom = origin["y"] + spacing["y"]
    reg_paths_agree = (
        right_points
        and bottom_points
        and abs(max(x for x, _ in right_points) - expected_right) < 1e-6
        and abs(min(y for _, y in right_points) - origin["y"]) < 1e-6
        and abs(min(x for x, _ in bottom_points) - origin["x"]) < 1e-6
        and abs(max(y for _, y in bottom_points) - expected_bottom) < 1e-6
    )
    check(
        "registration-coordinate-agreement",
        bool(reg_layer_agrees and top_left_agrees and reg_paths_agree),
        f"origin={origin}, spacing={spacing}",
    )

    metadata_stickers = {sticker["id"]: sticker for sticker in stickers}
    svg_cut_agrees = True
    for path in cut_paths:
        sticker = metadata_stickers.get(path.get("data-sticker-id", ""))
        svg_points = _path_points(path.get("d", ""))
        if sticker is None:
            svg_cut_agrees = False
            continue
        metadata_points = [tuple(point) for point in sticker["cut_contour_mm"][:-1]]
        svg_cut_agrees = svg_cut_agrees and len(svg_points) == len(metadata_points) and all(
            abs(svg_x - meta_x) < 1e-5 and abs(svg_y - meta_y) < 1e-5
            for (svg_x, svg_y), (meta_x, meta_y) in zip(svg_points, metadata_points)
        )
    check("cut-path-coordinate-agreement", svg_cut_agrees, f"checked={len(cut_paths)}")

    expected_input_scale = 25.4 / metadata["input"]["dpi"]
    transform = metadata["coordinate_transforms"]["input_pixels_to_page_mm"]
    check(
        "input-pixel-to-mm-transform",
        abs(transform[0][0] - expected_input_scale) < 1e-12 and abs(transform[1][1] - expected_input_scale) < 1e-12,
        f"scale={transform[0][0]:.12g} mm/px, expected={expected_input_scale:.12g}",
    )
    expected_print_scale = render["dpi"] / 25.4
    print_transform = metadata["coordinate_transforms"]["page_mm_to_print_pixels"]
    check(
        "page-mm-to-print-transform",
        abs(print_transform[0][0] - expected_print_scale) < 1e-12 and abs(print_transform[1][1] - expected_print_scale) < 1e-12,
        f"scale={print_transform[0][0]:.12g} px/mm, expected={expected_print_scale:.12g}",
    )

    all_safe = True
    closed = True
    bbox_agrees = True
    for sticker in stickers:
        contour = sticker["cut_contour_mm"]
        closed = closed and len(contour) >= 4 and contour[0] == contour[-1]
        xs = [point[0] for point in contour]
        ys = [point[1] for point in contour]
        bbox = sticker["cut_bbox_mm"]
        bbox_agrees = bbox_agrees and all(
            abs(actual - expected) < 2e-4
            for actual, expected in ((min(xs), bbox["left"]), (max(xs), bbox["right"]), (min(ys), bbox["top"]), (max(ys), bbox["bottom"]))
        )
        all_safe = all_safe and (
            bbox["left"] >= safe["left"] - 1e-6
            and bbox["top"] >= safe["top"] - 1e-6
            and bbox["right"] <= safe["right"] + 1e-6
            and bbox["bottom"] <= safe["bottom"] + 1e-6
        )
    check("closed-cut-contours", closed, f"checked={len(stickers)}")
    check("contour-bbox-agreement", bbox_agrees, f"checked={len(stickers)}")
    check("registration-safe-layout", all_safe, f"safe_rect_mm={safe}")

    intersecting_pairs = []
    polygons = {
        sticker["id"]: Polygon(sticker["cut_contour_mm"])
        for sticker in stickers
    }
    polygon_items = list(polygons.items())
    for index, (first_id, first_polygon) in enumerate(polygon_items):
        for second_id, second_polygon in polygon_items[index + 1 :]:
            if first_polygon.intersects(second_polygon):
                intersecting_pairs.append([first_id, second_id])
    check(
        "nonintersecting-cut-contours",
        not intersecting_pairs,
        f"conflicting_pairs={intersecting_pairs}",
    )
    recorded_pairs = sorted(
        sorted(conflict["sticker_ids"])
        for conflict in metadata.get("cut_safety", {}).get("contour_conflicts", [])
    )
    check(
        "contour-conflict-metadata",
        recorded_pairs == sorted(intersecting_pairs),
        f"recorded={recorded_pairs}, detected={sorted(intersecting_pairs)}",
    )

    for output_name, output in metadata.get("outputs", {}).items():
        path = output_dir / output["file"]
        actual = _sha256(path) if path.is_file() else "missing"
        check(f"sha256:{output_name}", actual == output["sha256"], f"actual={actual}")

    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def write_verify_report(output_dir: Path) -> dict:
    report = verify_output(output_dir)
    (output_dir / "verify-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
