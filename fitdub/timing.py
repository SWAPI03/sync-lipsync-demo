"""Predict how long a line takes to speak, before paying for text to speech.

The priors are rough characters per second for ElevenLabs voices at default speed. After the
first real TTS call for a language, the measured rate replaces the prior for the rest of the run.
"""

LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "hi": "Hindi",
    "ja": "Japanese",
}

CHARS_PER_SECOND = {"en": 15.0, "es": 15.5, "fr": 15.0, "de": 14.5, "pt": 15.0, "it": 15.0, "hi": 12.5, "ja": 7.5}
DEFAULT_CPS = 14.0

# TTS adds a little trailing silence, and cut_off can drop that much without losing words
TOLERANCE_S = 0.3
# only skip the TTS call when the prediction is clearly too long, the priors are rough
PRECHECK_SLACK = 1.15


def cps_for(lang: str, measured: float | None = None) -> float:
    return measured or CHARS_PER_SECOND.get(lang, DEFAULT_CPS)


def predict_seconds(text: str, lang: str, cps: float | None = None) -> float:
    return round(len(text.strip()) / cps_for(lang, cps), 2)


def char_budget(target_s: float, lang: str, cps: float | None = None, margin: float = 0.92) -> int:
    """How many characters fit in target_s, with a small margin for pauses."""
    return max(10, int(target_s * cps_for(lang, cps) * margin))


def fits(seconds: float, target_s: float) -> bool:
    return seconds <= target_s + TOLERANCE_S


def clearly_too_long(predicted_s: float, target_s: float) -> bool:
    return predicted_s > target_s * PRECHECK_SLACK
