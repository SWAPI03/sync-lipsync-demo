from fitdub.costs import Ledger
from fitdub.fit import fit_line
from fitdub.sync_api import Audio
from fitdub.translate import Line


class FakeAdapter:
    """Returns scripted lines, so the loop can be tested without an LLM."""

    lang = "de"

    def __init__(self, lines):
        self.lines = list(lines)
        self.calls = []

    def first(self, seconds, chars):
        self.calls.append(("first", chars))
        return Line(text=self.lines.pop(0))

    def shorter(self, took, target, chars, measured=True):
        self.calls.append(("shorter", round(took, 1), chars, measured))
        return Line(text=self.lines.pop(0))


class FakeTTS:
    """Speaks at a fixed 15 characters per second."""

    dry_run = False

    def __init__(self):
        self.calls = 0

    def tts(self, script, voice_id, out_dir, name, lang=""):
        self.calls += 1
        return Audio(f"https://example/{name}.mp3", f"{name}.mp3", round(len(script) / 15, 2))


def test_rewrites_after_a_measured_overrun(tmp_path):
    # 132 chars passes the precheck (9.1 s at the German prior) but the voice takes 8.8 s,
    # too long for an 8 s clip; 105 chars = 7 s fits
    adapter, api = FakeAdapter(["x" * 132, "y" * 105]), FakeTTS()
    take = fit_line(adapter, api, "voice", 8.0, Ledger(1.0), tmp_path)
    assert take.fits and api.calls == 2 and take.seconds == 7.0
    assert adapter.calls[1][:2] == ("shorter", 8.8) and adapter.calls[1][3] is True
    # the rewrite budget uses the measured rate of the real voice (15 cps), not the German prior
    assert adapter.calls[1][2] == int(8.0 * 15 * 0.92)


def test_precheck_skips_tts_for_a_clearly_long_line(tmp_path):
    adapter, api = FakeAdapter(["z" * 300, "y" * 105]), FakeTTS()
    take = fit_line(adapter, api, "voice", 8.0, Ledger(1.0), tmp_path)
    assert take.fits and api.calls == 1  # the 300 char line never reached TTS
    assert take.attempts[0].measured_s is None and adapter.calls[1][3] is False


def test_gives_up_instead_of_cutting_words(tmp_path):
    adapter, api = FakeAdapter(["x" * 132] * 3), FakeTTS()
    take = fit_line(adapter, api, "voice", 8.0, Ledger(1.0), tmp_path, max_rewrites=2)
    assert not take.fits and api.calls == 3
