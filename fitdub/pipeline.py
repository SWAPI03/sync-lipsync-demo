"""One function that runs the whole flow, shared by the CLI and the Gradio app."""

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .costs import (
    BILLING_FPS,
    FREE_LIPSYNC_PER_MONTH,
    PLAN_MAX_SECONDS,
    BudgetExceeded,
    Ledger,
    estimate_lipsync,
    estimate_tts,
    lipsync_frames,
)
from .fit import Take, fit_line
from .media import download, is_url, probe
from .sync_api import Audio, DryRunAPI, Lipsync, SyncAPI
from .timing import LANGUAGES, PRECHECK_SLACK, predict_seconds
from .translate import Adapter

DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"  # the ElevenLabs voice used in sync's docs


@dataclass
class LangResult:
    take: Take
    lipsync: Lipsync | None = None
    output_fps: float | None = None
    billed_frames: int | None = None
    skipped: str | None = None


@dataclass
class RunResult:
    results: list[LangResult]
    translator: str
    ledger: Ledger
    out_dir: Path
    clip_s: float
    fps: float
    plan: str
    seconds: float

    def summary(self) -> str:
        note = "\n(free plan: nothing is charged, amounts are Hobbyist list prices)" if self.plan == "free" else ""
        return self.ledger.summary() + note


def check_limits(plan: str, clip_s: float, n_langs: int) -> None:
    """Plan limits, checked before any call. A generation over them would just be rejected."""
    limit = PLAN_MAX_SECONDS[plan]
    if clip_s > limit:
        raise BudgetExceeded(f"the clip is {clip_s:.1f}s but the {plan} plan allows {limit}s per generation, trim it first")
    if plan == "free" and n_langs > FREE_LIPSYNC_PER_MONTH:
        raise BudgetExceeded(f"{n_langs} languages need {n_langs} lipsync generations, the free plan has {FREE_LIPSYNC_PER_MONTH} a month")


def run(
    script: str,
    video: str,
    languages: list[str],
    voice_id: str = DEFAULT_VOICE,
    budget: float = 2.0,
    dry_run: bool = True,
    model: str = "lipsync-2",
    plan: str = "free",
    max_rewrites: int = 2,
    clip_s: float | None = None,
    fps: float | None = None,
    use_llm: bool = True,
    out_root: Path = Path("outputs"),
) -> RunResult:
    start = time.time()
    if not script.strip():
        raise ValueError("the script is empty")
    unknown = [lang for lang in languages if lang not in LANGUAGES]
    if unknown:
        raise ValueError(f"unknown language codes {unknown}, use {sorted(LANGUAGES)}")

    out_dir = out_root / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    if clip_s is None:
        local = download(video, out_dir / "source.mp4") if is_url(video) else video
        clip_s, probed_fps = probe(local)
        fps = fps or probed_fps
    fps = fps or BILLING_FPS

    # check the whole run up front, so we never pay for two languages and then hit the limit
    check_limits(plan, clip_s, len(languages))
    ledger = Ledger(budget)
    worst_tts = (1 + max_rewrites) * estimate_tts(clip_s * PRECHECK_SLACK)
    ledger.reserve("whole run (worst case)", len(languages) * (estimate_lipsync(model, clip_s, fps) + worst_tts))

    if dry_run:
        api = DryRunAPI(predict_seconds)
    else:
        key = os.getenv("SYNC_API_KEY")
        if not key:
            raise RuntimeError("SYNC_API_KEY is not set (put it in .env)")
        api = SyncAPI(key)

    results, translator = [], "passthrough (no LLM key)"
    for lang in languages:
        lang_dir = out_dir / lang
        adapter = Adapter(script, lang, use_llm)
        translator = adapter.source
        take = fit_line(adapter, api, voice_id, clip_s, ledger, lang_dir, max_rewrites)
        if not take.fits:
            reason = f"still {take.seconds:.1f}s for a {clip_s:.1f}s clip after {take.tts_calls} TTS takes, skipped rather than cut words"
            results.append(LangResult(take, skipped=reason))
            continue
        results.append(lipsync(api, video, take, model, fps, ledger, lang_dir, f"fitdub-{out_dir.name}-{lang}", dry_run))

    result = RunResult(results, translator, ledger, out_dir, clip_s, fps, plan, round(time.time() - start, 1))
    _save(result, script, video, voice_id, model, dry_run)
    return result


def lipsync(api, video, take: Take, model, fps, ledger, lang_dir, key, dry_run) -> LangResult:
    billable = min(take.target_s, take.seconds)  # cut_off bills the shorter of video and audio
    label = f"{take.lang} lipsync ({billable:.1f}s)"
    est = estimate_lipsync(model, billable, fps)
    ledger.reserve(label, est)
    api_est = api.estimate(model, billable, fps)
    res = api.lipsync(video, Audio(take.audio_url, take.audio_path, take.seconds), model, lang_dir / "lipsync.mp4", key)

    if dry_run:
        ledger.record(label + " [dry run]", est, 0.0, api_est)
        return LangResult(take, res)
    if res.status != "COMPLETED":
        ledger.record(label + f" [{res.status}]", est, 0.0, api_est)
        return LangResult(take, res, skipped=f"lipsync {res.status}: {res.error}")

    # billing counts output frames, so measure the output instead of trusting the input fps
    out_s, out_fps = probe(res.path)
    frames = lipsync_frames(out_s, out_fps)
    ledger.record(label, est, estimate_lipsync(model, out_s, out_fps), api_est)
    return LangResult(take, res, out_fps, frames)


def _save(r: RunResult, script, video, voice_id, model, dry_run) -> None:
    # keep a record of every run next to its outputs
    (r.out_dir / "run.json").write_text(
        json.dumps(
            {
                "script": script,
                "video": video,
                "clip_seconds": r.clip_s,
                "clip_fps": r.fps,
                "voice_id": voice_id,
                "model": model,
                "plan": r.plan,
                "translator": r.translator,
                "dry_run": dry_run,
                "languages": [
                    {
                        **x.take.to_dict(),
                        "lipsync": asdict(x.lipsync) if x.lipsync else None,
                        "output_fps": x.output_fps,
                        "billed_frames": x.billed_frames,
                        "skipped": x.skipped,
                    }
                    for x in r.results
                ],
                "ledger": [asdict(e) for e in r.ledger.entries],
                "seconds": r.seconds,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
