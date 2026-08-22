#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy>=1.24",
#   "opencv-python-headless>=4.8",
#   "Pillow>=10.0",
#   "shapely>=2.0",
# ]
# ///

from sticker_cut.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
