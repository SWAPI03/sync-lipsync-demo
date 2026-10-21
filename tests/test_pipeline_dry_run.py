import json

import pytest

from fitdub.costs import BudgetExceeded
from fitdub.pipeline import run

SCRIPT = "Hi, I am Swapnil. I build AI tools, and I made this demo to show how dubbing can fit any clip."


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    # no LLM and no sync key, so a test can never call a paid API
    for name in ("OPENAI_API_KEY", "LLM_API_KEY", "SYNC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_dry_run_end_to_end(tmp_path):
    r = run(SCRIPT, "clip.mp4", ["hi", "es"], dry_run=True, clip_s=6.0, fps=30, out_root=tmp_path)
    assert [x.take.lang for x in r.results] == ["hi", "es"]
    assert all(x.take.fits and x.take.seconds <= 6.3 for x in r.results)
    assert r.ledger.spent == 0
    record = json.loads((r.out_dir / "run.json").read_text(encoding="utf-8"))
    assert record["translator"].startswith("passthrough") and record["clip_fps"] == 30
    assert len(record["languages"]) == 2 and record["languages"][0]["tts_calls"] >= 1


def test_free_plan_limits_are_checked_first(tmp_path):
    with pytest.raises(BudgetExceeded, match="20s per generation"):
        run(SCRIPT, "clip.mp4", ["hi"], clip_s=25.0, fps=30, out_root=tmp_path)
    with pytest.raises(BudgetExceeded, match="3 a month"):
        run(SCRIPT, "clip.mp4", ["hi", "es", "de", "fr"], clip_s=6.0, fps=30, out_root=tmp_path)


def test_budget_stops_the_run_before_any_call(tmp_path):
    # 3 languages of a 6 s, 30 fps clip need about $1.08 of lipsync alone
    with pytest.raises(BudgetExceeded, match="whole run"):
        run(SCRIPT, "clip.mp4", ["hi", "es", "de"], budget=0.5, clip_s=6.0, fps=30, out_root=tmp_path)
