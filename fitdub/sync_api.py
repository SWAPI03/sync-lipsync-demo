"""Thin wrapper over the sync. API (or a free dry run with the same interface).

Generations go through the official SDK (syncsdk). The SDK has no text to speech call and its
estimate takes inputs rather than a duration, so those go straight to the REST API with httpx.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .media import download, is_url, write_silence

BASE_URL = "https://api.sync.so/v2"
TERMINAL = {"COMPLETED", "FAILED", "REJECTED"}


@dataclass
class Audio:
    url: str | None  # hosted by sync, reusable as a lipsync input
    path: str  # local copy next to the run
    seconds: float


@dataclass
class Lipsync:
    id: str
    status: str
    output_seconds: float | None
    path: str | None
    error: str | None = None


class SyncAPI:
    dry_run = False

    def __init__(self, api_key: str):
        import httpx
        from sync import Sync

        self.http = httpx.Client(base_url=BASE_URL, headers={"x-api-key": api_key}, timeout=120)
        self.sdk = Sync(api_key=api_key)

    def voices(self) -> list[dict]:
        r = self.http.get("/voices", params={"provider": "elevenlabs"})
        r.raise_for_status()
        return r.json()

    def tts(self, script: str, voice_id: str, out_dir: Path, name: str, lang: str = "") -> Audio:
        # ElevenLabs multilingual voices read any language, lang is only used by the dry run
        r = self.http.post(
            "/tts",
            json={"script": script, "provider": "elevenlabs", "voiceId": voice_id, "stability": 0.5, "similarityBoost": 0.75},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"TTS failed ({r.status_code}): {r.text[:300]}")
        body = r.json()
        suffix = Path(urlparse(body["url"]).path).suffix or ".mp3"
        path = download(body["url"], out_dir / f"{name}{suffix}")
        return Audio(body["url"], str(path), float(body["duration"]))

    def estimate(self, model: str, seconds: float, fps: float) -> float | None:
        """sync's own price for a generation. Free: no media is fetched and nothing is created."""
        r = self.http.post("/generations/estimate", json={"model": model, "duration": seconds, "fps": fps})
        if r.status_code >= 400:
            return None
        return r.json().get("estimatedGenerationCost")

    def lipsync(
        self, video: str, audio: Audio, model: str, out_path: Path, key: str, sync_mode: str = "cut_off", timeout_s: int = 900
    ) -> Lipsync:
        from sync.common import Audio as AudioIn, GenerationOptions, Video

        # the idempotency key makes the SDK's retries safe: a retried create can never
        # start (and bill) a second generation
        opts = {"additional_headers": {"Idempotency-Key": key}, "max_retries": 2}
        options = GenerationOptions(sync_mode=sync_mode)
        if is_url(video) and audio.url:
            gen = self.sdk.generations.create(
                model=model, input=[Video(url=video), AudioIn(url=audio.url)], options=options, request_options=opts
            )
        else:
            with open(video, "rb") as v, open(audio.path, "rb") as a:
                gen = self.sdk.generations.create_with_files(
                    model=model, video=v, audio=a, options=options, request_options=opts
                )

        deadline = time.time() + timeout_s
        while gen.status not in TERMINAL and time.time() < deadline:
            time.sleep(5)
            gen = self.sdk.generations.get(gen.id)
        if gen.status != "COMPLETED" or not gen.output_url:
            return Lipsync(gen.id, gen.status, None, None, gen.error or "timed out")
        download(gen.output_url, out_path)
        return Lipsync(gen.id, gen.status, gen.output_duration, str(out_path))


class DryRunAPI:
    """Same interface, zero network calls. TTS length comes from the speaking rate model."""

    dry_run = True

    def __init__(self, predict):
        self.predict = predict  # (text, lang) -> seconds

    def voices(self) -> list[dict]:
        return []

    def tts(self, script: str, voice_id: str, out_dir: Path, name: str, lang: str = "") -> Audio:
        seconds = round(self.predict(script, lang) + 0.2, 2)  # real TTS adds a little silence at the end
        path = write_silence(out_dir / f"{name}.wav", seconds)
        return Audio(None, str(path), seconds)

    def estimate(self, model: str, seconds: float, fps: float) -> float | None:
        return None

    def lipsync(self, video, audio: Audio, model, out_path, key, sync_mode="cut_off", timeout_s=0) -> Lipsync:
        return Lipsync("dry-run", "DRY_RUN", audio.seconds, None)
