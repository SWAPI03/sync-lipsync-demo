"""Command-line entry point.

    python cli.py "Hi, I build AI tools..." --video clip.mp4 --langs hi,es,de --dry-run
    python cli.py "Hi, I build AI tools..." --video clip.mp4 --langs hi,es,de --budget 2
    python cli.py --check     # free: are keys set, which voices work, sync's estimate at 25 vs 30 fps
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()
# Windows consoles default to cp1252, which cannot print Hindi or Japanese lines
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fitdub.costs import BudgetExceeded, PLAN_MAX_SECONDS, estimate_lipsync  # noqa: E402
from fitdub.pipeline import DEFAULT_VOICE, run  # noqa: E402


def check() -> None:
    """Free calls only: nothing here creates a generation or uses the monthly allowance."""
    key = os.getenv("SYNC_API_KEY")
    llm = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    print(f"SYNC_API_KEY: {'set' if key else 'NOT set'}   LLM key: {'set' if llm else 'not set (passthrough)'}")
    if not key:
        return
    from fitdub.sync_api import SyncAPI

    api = SyncAPI(key)
    voices = api.voices()
    usable = [v for v in voices if not v.get("restriction")]
    print(f"{len(voices)} voices, {len(usable)} usable, for example:")
    for v in usable[:8]:
        print(f"  {v['id']}  {v.get('name', '')}")
    for fps in (25, 30):
        print(f"lipsync-2, 8 s at {fps} fps: sync says ${api.estimate('lipsync-2', 8, fps)}, we estimate ${estimate_lipsync('lipsync-2', 8, fps)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Script -> translation that fits the clip -> sync. TTS -> sync. lipsync")
    p.add_argument("script", nargs="?", help="what the person in the clip should say (English)")
    p.add_argument("--video", help="local clip or public URL of a short talking head video")
    p.add_argument("--langs", default="hi,es,de", help="comma separated codes, e.g. hi,es,de,fr,ja")
    p.add_argument("--voice", default=os.getenv("SYNC_VOICE_ID", DEFAULT_VOICE), help="ElevenLabs voice id")
    p.add_argument("--model", default="lipsync-2", help="lipsync-2, lipsync-2-pro, lipsync-1.9.0-beta")
    p.add_argument("--plan", default="free", choices=sorted(PLAN_MAX_SECONDS), help="your sync plan, for its limits")
    p.add_argument("--budget", type=float, default=2.0, help="max dollars this run may spend")
    p.add_argument("--rewrites", type=int, default=2, help="max shorter rewrites per language after TTS")
    p.add_argument("--seconds", type=float, help="clip length, skips probing the video")
    p.add_argument("--dry-run", action="store_true", help="no sync calls, no cost")
    p.add_argument("--no-llm", action="store_true", help="skip translation (with --dry-run: zero API calls)")
    p.add_argument("--check", action="store_true", help="check keys, voices and pricing with free calls only")
    args = p.parse_args()

    if args.check:
        return check()
    if not args.script or not args.video:
        p.error("a script and --video are required (or use --check)")

    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    try:
        r = run(
            args.script,
            args.video,
            langs,
            args.voice,
            args.budget,
            args.dry_run,
            args.model,
            args.plan,
            args.rewrites,
            args.seconds,
            use_llm=not args.no_llm,
        )
    except BudgetExceeded as err:
        raise SystemExit(f"Stopped before spending: {err}")

    print(f"\nclip {r.clip_s:.1f}s at {r.fps:g} fps, translated by {r.translator}, {r.seconds}s total")
    for x in r.results:
        t = x.take
        print(f"\n[{t.lang}] {'fits' if t.fits else 'does NOT fit'} after {len(t.attempts)} attempts, {t.tts_calls} TTS")
        for i, a in enumerate(t.attempts, 1):
            took = f"{a.measured_s:.1f}s measured" if a.measured_s is not None else "precheck only"
            print(f"  {i}. {a.chars} chars, predicted {a.predicted_s:.1f}s, {took}: {a.text}")
        if t.final and t.final.back_translation:
            print(f"     back: {t.final.back_translation}")
        if x.lipsync and x.lipsync.path:
            print(f"  video: {x.lipsync.path}  ({x.billed_frames} frames at {x.output_fps:g} fps)")
        if x.skipped:
            print(f"  skipped: {x.skipped}")
    print("\n" + r.summary())
    print(f"outputs: {r.out_dir}")


if __name__ == "__main__":
    main()
