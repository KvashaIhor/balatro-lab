"""Render a viewer scene in headless Chrome and compare it with a game screenshot, pixel by pixel.

Usage:  python3 scripts/compare_scene.py the-wall ref/the_wall.jpg [--port 8643]
Output: ref/out/<scene>-ours.png, <scene>-side.png (game | ours), <scene>-diff.png (error heat map),
        and the mean error per screen region (0 = identical, 255 = opposite), lowest-hanging fruit first.
Needs the Lab server running (python3 app/server.py) and Google Chrome.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Named regions of the 1920 x 1080 screen: (left, top, right, bottom).
REGIONS = {
    "sidebar: blind": (73, 79, 499, 384), "sidebar: round score": (73, 390, 499, 476),
    "sidebar: hand": (73, 478, 499, 694), "sidebar: buttons": (90, 705, 225, 1030),
    "sidebar: stats": (232, 700, 495, 1032), "jokers": (515, 50, 1370, 310), "consumables": (1390, 50, 1790, 310),
    "played cards": (580, 360, 1510, 720), "hand": (530, 790, 1560, 1050), "deck": (1580, 800, 1760, 1050),
    "background (left strip)": (0, 0, 66, 1080), "background (board)": (505, 720, 1920, 790),
}


def shoot(scene: str, port: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([CHROME, "--headless=new", f"--user-data-dir={profile}", "--hide-scrollbars",
                        "--force-device-scale-factor=1", "--window-size=1920,1080", "--virtual-time-budget=5000",
                        f"--screenshot={out}", f"http://127.0.0.1:{port}/#scene={scene}"],
                       check=True, capture_output=True, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scene")
    parser.add_argument("reference")
    parser.add_argument("--port", type=int, default=8643)
    args = parser.parse_args()
    out_dir = ROOT / "ref" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    ours_path = out_dir / f"{args.scene}-ours.png"
    shoot(args.scene, args.port, ours_path)

    ref = Image.open(ROOT / args.reference).convert("RGB")
    ours = Image.open(ours_path).convert("RGB").resize(ref.size)
    a, b = np.asarray(ref).astype(int), np.asarray(ours).astype(int)
    err = np.abs(a - b).mean(axis=2)
    side = Image.new("RGB", (ref.width * 2, ref.height))
    side.paste(ref, (0, 0))
    side.paste(ours, (ref.width, 0))
    side.save(out_dir / f"{args.scene}-side.png")
    heat = np.clip(err * 3, 0, 255).astype(np.uint8)
    Image.fromarray(np.stack([heat, heat // 3, 255 - heat], axis=2)).save(out_dir / f"{args.scene}-diff.png")

    print(f"overall mean error {err.mean():.1f}")
    rows = [(err[t:btm, l:r].mean(), name) for name, (l, t, r, btm) in REGIONS.items()]
    for e, name in sorted(rows, reverse=True):
        print(f"  {e:6.1f}  {name}")
    print(f"images in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
