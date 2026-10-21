"""Translate a script for dubbing, under a length limit, and shorten it on feedback.

Uses any OpenAI-compatible endpoint (OpenAI, Groq, Gemini's OpenAI endpoint), set with
LLM_BASE_URL / LLM_MODEL / LLM_API_KEY. Without a key it falls back to passing the script
through and trimming words, so the rest of the pipeline can still be tried for free.
"""

import json
import os

from pydantic import BaseModel, Field, ValidationError

from .timing import LANGUAGES

SYSTEM_PROMPT = """You are a dubbing translator. Translate the script into {language} so a voice
actor can say it over an existing video clip of someone speaking.
Return ONLY JSON: {{"text": str, "back_translation": str}}
Rules:
- text: natural spoken {language} in its native script, the way a native speaker would say it.
  Keep names, brands and numbers.
- Translate faithfully first. It must be speakable in at most {seconds:.1f} seconds, which is
  about {chars} characters, so only condense if a faithful version would be longer than that.
  Then drop filler words before you drop meaning.
- back_translation: a literal English translation of your text, so a reviewer can check meaning
- No quotes, stage directions or emojis"""


class Line(BaseModel):
    text: str = Field(min_length=1)
    back_translation: str = ""


class Adapter:
    """One conversation per target language, so rewrites see the earlier attempts."""

    def __init__(self, script: str, lang: str, use_llm: bool = True):
        self.script = script.strip()
        self.lang = lang
        self.language = LANGUAGES.get(lang, lang)
        api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")) if use_llm else None
        self.model = os.getenv("LLM_MODEL", "gpt-4.1-mini") if api_key else None
        self.source = self.model or "passthrough (no LLM key)"
        self.messages: list[dict] = []
        if api_key:
            from openai import OpenAI

            self.client = OpenAI(api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None)

    def first(self, seconds: float, chars: int) -> Line:
        if not self.model:
            return trim(Line(text=self.script, back_translation=self.script), chars)
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(language=self.language, seconds=seconds, chars=chars)},
            {"role": "user", "content": self.script},
        ]
        return self._ask()

    def shorter(self, took: float, target: float, chars: int, measured: bool = True) -> Line:
        if not self.model:
            return trim(Line(text=self.script, back_translation=self.script), chars)
        how = "Spoken by the TTS voice that took" if measured else "That would take about"
        cut = round(100 * (1 - target / took))
        self.messages.append(
            {
                "role": "user",
                "content": f"{how} {took:.1f} s but the clip is only {target:.1f} s. Rewrite it about {cut}% "
                f"shorter, at most {chars} characters, keeping the core meaning. Same JSON shape.",
            }
        )
        return self._ask()

    def _ask(self) -> Line:
        # one retry with the validation error fed back, then give up
        for _ in range(2):
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = resp.choices[0].message.content or ""
            self.messages.append({"role": "assistant", "content": raw})
            try:
                return Line.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as err:
                self.messages.append({"role": "user", "content": f"That was invalid ({err}). Return only valid JSON."})
        raise RuntimeError(f"LLM returned invalid JSON twice for {self.language}")


def trim(line: Line, chars: int) -> Line:
    """Cut at a word boundary. Only used without an LLM, to exercise the loop in dry runs."""
    if len(line.text) <= chars:
        return line
    text = line.text[:chars].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return Line(text=text, back_translation=text)
