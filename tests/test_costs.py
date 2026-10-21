import pytest

from fitdub.costs import BudgetExceeded, Ledger, estimate_lipsync, estimate_tts


def test_lipsync_is_priced_per_output_frame():
    assert estimate_lipsync("lipsync-2", 8, fps=25) == 0.40
    # the per second price assumes 25 fps, so a 30 fps phone clip costs 20% more
    assert estimate_lipsync("lipsync-2", 8, fps=30) == 0.48
    assert estimate_lipsync("lipsync-2-pro", 10, fps=25) == 0.83


def test_tts_rounds_up_to_whole_seconds():
    assert estimate_tts(7.2) == 0.032


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        estimate_lipsync("made-up-model", 5)


def test_ledger_blocks_before_overspending():
    ledger = Ledger(budget=1.0)
    ledger.reserve("a", 0.48)
    ledger.record("a", 0.48, 0.48)
    ledger.reserve("b", 0.48)
    ledger.record("b", 0.48, 0.50)  # billing can come out a little above the estimate
    assert ledger.spent == 0.98
    with pytest.raises(BudgetExceeded):
        ledger.reserve("c", 0.40)
