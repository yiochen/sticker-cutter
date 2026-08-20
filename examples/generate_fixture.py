#!/usr/bin/env python3
"""Generate the deterministic transparent sticker sheet used for visual QA."""

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    output = Path(__file__).with_name("synthetic-stickers.png")
    image = Image.new("RGBA", (800, 700), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 70, 260, 260), fill=(255, 173, 31, 255))
    draw.rounded_rectangle((350, 60, 610, 270), radius=45, fill=(65, 180, 160, 255))
    draw.polygon(((140, 620), (190, 390), (260, 570), (75, 440), (295, 440)), fill=(105, 95, 210, 255))
    draw.polygon(((440, 390), (675, 430), (590, 635), (370, 575)), fill=(225, 75, 130, 255))
    # Deliberate one-pixel artifact: it should print but never become a cut.
    draw.point((5, 5), fill="black")
    image.save(output, dpi=(254, 254))
    print(output)


if __name__ == "__main__":
    main()
