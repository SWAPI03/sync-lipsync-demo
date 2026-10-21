"""Build a side by side GIF (original and each dub) from one or more finished runs, for the README.

    python scripts/make_gif.py assets/dubs.gif outputs/<run-folder> [outputs/<another-run>]

Set CROP=w:h:x:y (ffmpeg crop, in source pixels) to zoom in on the face.
"""

import json
import os
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

LANG_NAMES = {"hi": "Hindi", "es": "Spanish", "de": "German", "fr": "French", "pt": "Portuguese", "it": "Italian", "ja": "Japanese"}
FPS, WIDTH, MAX_SECONDS = 10, 220, 5.0
CROP = os.getenv("CROP")


def frames(path: Path, seconds: float) -> list[Image.Image]:
    vf = f"crop={CROP},fps={FPS}" if CROP else f"fps={FPS}"
    reader = imageio_ffmpeg.read_frames(str(path), output_params=["-vf", vf])
    w, h = next(reader)["size"]
    size = (WIDTH, round(h * WIDTH / w))
    out = [Image.frombytes("RGB", (w, h), f).resize(size) for f in reader]
    return out[: int(seconds * FPS)]


def main(out: Path, run_dirs: list[Path]) -> None:
    records = [json.loads((d / "run.json").read_text(encoding="utf-8")) for d in run_dirs]
    first = run_dirs[0]
    source = first / "source.mp4" if (first / "source.mp4").exists() else Path(records[0]["video"])
    langs = [x for r in records for x in r["languages"] if x.get("lipsync") and x["lipsync"].get("path")]
    panels = [("Original", source)] + [(LANG_NAMES.get(x["lang"], x["lang"]), Path(x["lipsync"]["path"])) for x in langs]
    seconds = min(MAX_SECONDS, records[0]["clip_seconds"], *[x["seconds"] for x in langs])
    clips = [(label, frames(path, seconds)) for label, path in panels]
    n = min(len(c) for _, c in clips)
    w, h = clips[0][1][0].size

    gif = []
    for i in range(n):
        canvas = Image.new("RGB", (w * len(clips), h + 28), (17, 17, 17))
        draw = ImageDraw.Draw(canvas)
        for j, (label, c) in enumerate(clips):
            canvas.paste(c[i].resize((w, h)), (j * w, 28))
            draw.text((j * w + 8, 8), label, fill=(255, 255, 255))
        gif.append(canvas)
    out.parent.mkdir(parents=True, exist_ok=True)
    gif[0].save(out, save_all=True, append_images=gif[1:], duration=1000 // FPS, loop=0, optimize=True)
    print(f"{out}: {len(clips)} panels, {n} frames, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), [Path(a) for a in sys.argv[2:]])
