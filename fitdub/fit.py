"""The fit loop: get a translated line that is short enough to speak over the clip.

With sync_mode cut_off, audio longer than the video is clipped, so an overlong translation
loses its last words. Other modes move the problem into the video (bounce plays it backwards,
loop repeats it, remap slows it down). So the line itself has to fit before lipsync runs:

  translate under a character budget
  -> if the prediction is clearly too long, ask for a shorter line (no TTS spent)
  -> TTS, measure the real duration, recalibrate characters per second for this voice
  -> if it still runs long, feed the measured overrun back and rewrite
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .costs import Ledger, estimate_tts
from .timing import char_budget, clearly_too_long, fits, predict_seconds
from .translate import Adapter


@dataclass
class Attempt:
    text: str
    back_translation: str
    chars: int
    predicted_s: float
    measured_s: float | None  # None when the precheck rejected it without paying for TTS


@dataclass
class Take:
    lang: str
    target_s: float
    attempts: list[Attempt] = field(default_factory=list)
    fits: bool = False
    audio_url: str | None = None
    audio_path: str | None = None
    seconds: float | None = None
    tts_calls: int = 0
    measured_cps: float | None = None

    @property
    def final(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    def to_dict(self) -> dict:
        return asdict(self)


def fit_line(adapter: Adapter, api, voice_id: str, target_s: float, ledger: Ledger, out_dir: Path, max_rewrites: int = 2) -> Take:
    lang = adapter.lang
    take = Take(lang, target_s)
    cps = None  # use the language prior until we have measured this voice
    line = adapter.first(target_s, char_budget(target_s, lang))
    llm_calls, max_llm = 1, 2 * max_rewrites + 1

    while True:
        predicted = predict_seconds(line.text, lang, cps)
        if clearly_too_long(predicted, target_s) and llm_calls < max_llm:
            take.attempts.append(Attempt(line.text, line.back_translation, len(line.text), predicted, None))
            line = adapter.shorter(predicted, target_s, char_budget(target_s, lang, cps), measured=False)
            llm_calls += 1
            continue

        label = f"{lang} tts {take.tts_calls + 1}"
        est = estimate_tts(max(predicted, target_s))
        ledger.reserve(label, est)
        audio = api.tts(line.text, voice_id, out_dir, f"tts_{take.tts_calls + 1}", lang=lang)
        take.tts_calls += 1
        if api.dry_run:
            ledger.record(label + " [dry run]", est, 0.0)
        else:
            ledger.record(label, est, estimate_tts(audio.seconds))

        cps = len(line.text.strip()) / audio.seconds  # calibrate to the real voice
        take.measured_cps = round(cps, 2)
        take.attempts.append(Attempt(line.text, line.back_translation, len(line.text), predicted, audio.seconds))
        take.audio_url, take.audio_path, take.seconds = audio.url, audio.path, audio.seconds

        if fits(audio.seconds, target_s):
            take.fits = True
            return take
        if take.tts_calls > max_rewrites or llm_calls >= max_llm:
            return take
        line = adapter.shorter(audio.seconds, target_s, char_budget(target_s, lang, cps))
        llm_calls += 1
