from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image, ImageDraw

from sticker_cut.geometry import PreparationError, build_layout, page_spec, parse_mm
from sticker_cut.output import write_outputs
from sticker_cut.silhouette import run_dry_run
from sticker_cut.verify import verify_output


INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
SVG_NS = "http://www.w3.org/2000/svg"


def save_rgba(path: Path, size: tuple[int, int], draw_fn, dpi: float = 254.0) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(image))
    image.save(path, dpi=(dpi, dpi))


def test_lengths_and_page_names() -> None:
    assert parse_mm("2mm") == 2.0
    assert parse_mm("0.2cm") == 2.0
    assert parse_mm("1in") == 25.4
    assert page_spec("letter").width_mm == 215.9
    assert page_spec("123x234").height_mm == 234.0


def test_known_40mm_object_and_2mm_border(tmp_path: Path) -> None:
    source = tmp_path / "square.png"
    save_rgba(source, (800, 800), lambda draw: draw.rectangle((200, 200, 599, 599), fill="navy"))
    layout = build_layout(source, page=page_spec("letter"), input_dpi=254, border_mm=2)

    assert len(layout.stickers) == 1
    artwork = layout.stickers[0].artwork_bbox_mm
    cut = layout.stickers[0].cut_polygon.bounds
    assert artwork.width == pytest.approx(40.0, abs=0.01)
    assert artwork.height == pytest.approx(40.0, abs=0.01)
    assert cut[0] == pytest.approx(artwork.left - 2.0, abs=0.15)
    assert cut[1] == pytest.approx(artwork.top - 2.0, abs=0.15)
    assert cut[2] == pytest.approx(artwork.right + 2.0, abs=0.15)
    assert cut[3] == pytest.approx(artwork.bottom + 2.0, abs=0.15)


def test_multiple_shapes_and_noise_rejection(tmp_path: Path) -> None:
    source = tmp_path / "shapes.png"

    def draw_shapes(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((70, 70, 249, 249), fill="red")
        draw.ellipse((330, 70, 529, 269), fill="green")
        draw.polygon(((110, 560), (180, 330), (250, 560), (60, 420), (300, 420)), fill="blue")
        draw.polygon(((430, 350), (590, 380), (540, 560), (370, 510)), fill="purple")
        draw.point((5, 5), fill="black")

    save_rgba(source, (700, 650), draw_shapes)
    layout = build_layout(source, page=page_spec("letter"), input_dpi=254, border_mm=2, min_area_mm2=1)

    assert len(layout.stickers) == 4
    assert any("Ignored 1" in warning for warning in layout.warnings)
    assert all(sticker.cut_polygon.is_valid for sticker in layout.stickers)
    assert all(sticker.cut_polygon.exterior.is_closed for sticker in layout.stickers)


def test_holes_do_not_create_inner_blade_paths(tmp_path: Path) -> None:
    source = tmp_path / "donut.png"

    def draw_donut(draw: ImageDraw.ImageDraw) -> None:
        draw.ellipse((150, 150, 449, 449), fill="orange")
        draw.ellipse((260, 260, 339, 339), fill=(0, 0, 0, 0))

    save_rgba(source, (600, 600), draw_donut)
    layout = build_layout(source, page=page_spec("letter"), input_dpi=254, border_mm=2)

    assert len(layout.stickers) == 1
    assert len(layout.stickers[0].cut_polygon.interiors) == 0


@pytest.mark.parametrize("shape", ["rectangle", "circle", "star", "blob"])
def test_border_accuracy_across_synthetic_shapes(tmp_path: Path, shape: str) -> None:
    source = tmp_path / f"{shape}.png"

    def draw_shape(draw: ImageDraw.ImageDraw) -> None:
        if shape == "rectangle":
            draw.rectangle((180, 200, 419, 399), fill="red")
        elif shape == "circle":
            draw.ellipse((180, 180, 419, 419), fill="green")
        elif shape == "star":
            draw.polygon(((300, 160), (340, 260), (450, 260), (365, 330), (400, 440), (300, 375), (200, 440), (235, 330), (150, 260), (260, 260)), fill="blue")
        else:
            draw.polygon(((160, 250), (225, 155), (365, 175), (450, 280), (390, 420), (245, 445), (145, 360)), fill="purple")

    save_rgba(source, (600, 600), draw_shape)
    layout = build_layout(source, page=page_spec("letter"), input_dpi=254, border_mm=2)
    sticker = layout.stickers[0]
    artwork = sticker.artwork_bbox_mm
    cut = sticker.cut_polygon.bounds

    assert cut[0] == pytest.approx(artwork.left - 2, abs=0.18)
    assert cut[1] == pytest.approx(artwork.top - 2, abs=0.18)
    assert cut[2] == pytest.approx(artwork.right + 2, abs=0.18)
    assert cut[3] == pytest.approx(artwork.bottom + 2, abs=0.18)


def test_generated_artifacts_verify_and_use_upstream_layer_convention(tmp_path: Path) -> None:
    source = tmp_path / "two.png"
    save_rgba(
        source,
        (600, 500),
        lambda draw: (draw.ellipse((60, 80, 239, 259), fill="orange"), draw.rectangle((340, 180, 539, 379), fill="teal")),
    )
    layout = build_layout(source, page=page_spec("letter"), input_dpi=254, border_mm=2, output_dpi=150)
    output = tmp_path / "output"
    write_outputs(layout, output)
    report = verify_output(output)

    assert report["passed"], report
    root = ET.parse(output / "cut-sheet.svg").getroot()
    layers = {
        node.get(f"{{{INKSCAPE_NS}}}label")
        for node in root.findall(f".//{{{SVG_NS}}}g")
        if node.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
    }
    ids = {node.get("id") for node in root.iter()}
    assert {"Print", "Cut", "Regmarks"}.issubset(layers)
    assert {"regmark-tl", "regmark-tr", "regmark-bl"}.issubset(ids)
    metadata = json.loads((output / "metadata.json").read_text())
    assert metadata["sticker_count"] == 2
    assert metadata["coordinate_transforms"]["cut_paths"].startswith("SVG viewBox")


def test_page_safety_rejects_oversized_physical_input(tmp_path: Path) -> None:
    source = tmp_path / "huge.png"
    save_rgba(source, (2000, 2000), lambda draw: draw.rectangle((0, 0, 1999, 1999), fill="red"))
    with pytest.raises(PreparationError, match="registration-safe area"):
        build_layout(source, page=page_spec("letter"), input_dpi=254)


def test_dry_run_wrapper_captures_driver_diagnostics(tmp_path: Path) -> None:
    svg = tmp_path / "cut-sheet.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm">'
        '<g id="regmark" data-origin-x-mm="10" data-origin-y-mm="10"/></svg>'
    )
    driver = tmp_path / "sendto_silhouette.py"
    driver.write_text(
        "import pathlib, sys\n"
        "args = {item.split('=', 1)[0]: item.split('=', 1)[1] for item in sys.argv[1:] if '=' in item}\n"
        "is_reg = '--regmark=True' in sys.argv\n"
        "log = ('Detected Existing Registration Mark:: ok\\nUsing Registration Mark:: ok\\n' if is_reg else '')\n"
        "log += 'Logging 2 cut paths containing 44 points:\\nstatus=ready\\n'\n"
        "pathlib.Path(args['--logfile']).write_text(log)\n"
        "pathlib.Path(args['--cmdfile']).write_bytes(b'COMMANDS')\n"
        "if is_reg:\n"
        "    print(\"ValueError: Couldn't find registration marks. None\", file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
    )
    result = run_dry_run(svg, driver=driver)

    assert result["passed"]
    assert result["parsed_cut_paths"] == 2
    assert result["parsed_cut_points"] == 44
    assert result["registration"]["expected_no_hardware_sensor_stop"]
    assert (tmp_path / "dry-run" / "cutter-commands.bin").read_bytes() == b"COMMANDS"
