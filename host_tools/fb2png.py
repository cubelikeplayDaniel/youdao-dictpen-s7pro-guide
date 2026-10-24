#!/usr/bin/env python3
import sys
from PIL import Image

def fb2png(raw_path, png_path, rotate=270):
    with open(raw_path, "rb") as f:
        data = f.read(240 * 1020 * 4)
    # 240x1020 BGRA
    img = Image.frombytes("RGBA", (240, 1020), data, "raw", "BGRA")
    if rotate:
        # Rotate to landscape (1020x240)
        img = img.rotate(rotate, expand=True)
    img.save(png_path)
    print(f"Saved {png_path} ({img.size})")

if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fb.raw"
    png = sys.argv[2] if len(sys.argv) > 2 else "/tmp/screen.png"
    fb2png(raw, png)
