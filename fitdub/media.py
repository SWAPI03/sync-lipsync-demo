"""Small media helpers: probe a clip, download files, write silent audio for dry runs."""

import wave
from pathlib import Path


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def probe(path: str | Path) -> tuple[float, float]:
    """(duration in seconds, frames per second) of a video, using the ffmpeg bundled with imageio."""
    import imageio_ffmpeg

    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)
    reader.close()
    return float(meta["duration"]), float(meta["fps"])


def download(url: str, path: Path) -> Path:
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return path


def write_silence(path: Path, seconds: float, rate: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path
