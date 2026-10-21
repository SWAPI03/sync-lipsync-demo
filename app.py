"""Gradio UI: upload a short talking head clip, type a script, get it dubbed and lipsynced by sync."""

import os

import gradio as gr
from dotenv import load_dotenv

load_dotenv()

from fitdub.costs import BudgetExceeded, LIPSYNC_USD_PER_SECOND, PLAN_MAX_SECONDS  # noqa: E402
from fitdub.pipeline import DEFAULT_VOICE, run  # noqa: E402
from fitdub.timing import LANGUAGES  # noqa: E402

MAX_LANGS = 3


def generate(video_file, video_url, script, langs, voice, model, plan, budget, rewrites, dry_run):
    video = video_url.strip() or video_file
    if not video:
        raise gr.Error("Upload a clip or paste a public video URL.")
    if not script.strip():
        raise gr.Error("Write the script first.")
    if not langs or len(langs) > MAX_LANGS:
        raise gr.Error(f"Pick 1 to {MAX_LANGS} languages.")
    codes = [c for c, name in LANGUAGES.items() if name in langs]
    try:
        r = run(script, video, codes, voice.strip() or DEFAULT_VOICE, float(budget), dry_run, model, plan, int(rewrites))
    except (BudgetExceeded, ValueError) as err:
        raise gr.Error(f"Stopped before spending: {err}")

    rows, videos = [], []
    for x in r.results:
        for i, a in enumerate(x.take.attempts, 1):
            took = f"{a.measured_s:.1f}" if a.measured_s is not None else "precheck"
            rows.append([LANGUAGES[x.take.lang], i, a.chars, a.predicted_s, took, a.text, a.back_translation])
        videos.append(x.lipsync.path if x.lipsync and x.lipsync.path else None)
    videos += [None] * (MAX_LANGS - len(videos))
    fitted = sum(x.take.fits for x in r.results)
    header = (
        f"**Clip** {r.clip_s:.1f}s at {r.fps:g} fps. **{fitted}/{len(r.results)}** languages fit, "
        f"translated by `{r.translator}` in {r.seconds}s" + (" (dry run, no sync calls)" if dry_run else "")
    )
    skipped = "\n".join(f"{x.take.lang}: {x.skipped}" for x in r.results if x.skipped)
    return header, rows, *videos, r.summary() + (f"\n\n{skipped}" if skipped else "")


with gr.Blocks(title="Fit-to-clip dubbing on sync.") as demo:
    gr.Markdown(
        "# Fit-to-clip dubbing\nScript → LLM translation that fits the clip → sync. text to speech "
        "→ measured, rewritten if too long → sync. lipsync"
    )
    with gr.Row():
        with gr.Column(scale=1):
            video_file = gr.Video(label="Talking head clip (under 20 s on the free plan)", sources=["upload"])
            video_url = gr.Textbox(label="...or a public video URL", placeholder="https://assets.sync.so/docs/example-video.mp4")
            script = gr.Textbox(label="Script (English)", lines=3)
            langs = gr.CheckboxGroup(list(LANGUAGES.values()), value=["Hindi", "Spanish", "German"], label="Languages (max 3)")
            voice = gr.Textbox(value=os.getenv("SYNC_VOICE_ID", DEFAULT_VOICE), label="ElevenLabs voice id")
            model = gr.Dropdown(list(LIPSYNC_USD_PER_SECOND), value="lipsync-2", label="Lipsync model")
            plan = gr.Dropdown(list(PLAN_MAX_SECONDS), value="free", label="Your sync plan (for its limits)")
            budget = gr.Number(value=2.0, label="Budget for this run ($)")
            rewrites = gr.Slider(0, 3, value=2, step=1, label="Max rewrites after TTS")
            dry_run = gr.Checkbox(value=True, label="Dry run (no sync calls, no cost)")
            go = gr.Button("Dub it", variant="primary")
        with gr.Column(scale=2):
            header = gr.Markdown()
            table = gr.Dataframe(
                headers=["Language", "#", "Chars", "Predicted s", "Measured s", "Line", "Back translation"], wrap=True
            )
            with gr.Row():
                outs = [gr.Video(label=f"Result {i + 1}") for i in range(MAX_LANGS)]
            ledger = gr.Textbox(label="Cost ledger", lines=8)

    go.click(
        generate,
        [video_file, video_url, script, langs, voice, model, plan, budget, rewrites, dry_run],
        [header, table, *outs, ledger],
    )

if __name__ == "__main__":
    demo.launch()
