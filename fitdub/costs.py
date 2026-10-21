"""Dollar estimates and a spend ledger, so a run can never go over budget.

Rates are the Hobbyist / Creator prices from https://sync.so/docs/product/billing.
Lipsync is billed per output frame and the per second price assumes 25 fps, so a 30 fps
clip costs 1.2x the per second rate. Text to speech is billed per second of audio.
"""

import math
from dataclasses import dataclass, field

LIPSYNC_USD_PER_SECOND = {
    "lipsync-1.9.0-beta": 0.025,
    "lipsync-2": 0.05,
    "lipsync-2-pro": 0.083,
    "sync-3": 0.133,
}
BILLING_FPS = 25
TTS_USD_PER_SECOND = 0.004

# longest clip a single generation may use on each plan
PLAN_MAX_SECONDS = {"free": 20, "hobbyist": 60, "creator": 300, "growth": 600, "scale": 1800}
# the free plan allows 3 lipsync generations a month
FREE_LIPSYNC_PER_MONTH = 3


def lipsync_frames(seconds: float, fps: float) -> int:
    return math.ceil(round(seconds * fps, 6))


def estimate_lipsync(model: str, seconds: float, fps: float = BILLING_FPS) -> float:
    if model not in LIPSYNC_USD_PER_SECOND:
        raise ValueError(f"no price for lipsync model {model!r}")
    per_frame = LIPSYNC_USD_PER_SECOND[model] / BILLING_FPS
    return round(lipsync_frames(seconds, fps) * per_frame, 4)


def estimate_tts(seconds: float) -> float:
    return round(math.ceil(seconds) * TTS_USD_PER_SECOND, 4)


class BudgetExceeded(Exception):
    pass


@dataclass
class Entry:
    label: str
    estimated: float  # our own estimate, before the call
    api_estimate: float | None  # what sync's estimate endpoint said, when we asked it
    billed: float  # computed from what the API returned (output duration, audio duration)


@dataclass
class Ledger:
    budget: float
    entries: list[Entry] = field(default_factory=list)

    @property
    def spent(self) -> float:
        return round(sum(e.billed for e in self.entries), 4)

    @property
    def remaining(self) -> float:
        return round(self.budget - self.spent, 4)

    def reserve(self, label: str, estimate: float) -> None:
        """Refuse a job before it is sent if its estimate would break the budget."""
        if estimate > self.remaining + 1e-9:
            raise BudgetExceeded(f"{label} needs ~${estimate:.3f} but only ${self.remaining:.3f} of ${self.budget:.2f} remains")

    def record(self, label: str, estimated: float, billed: float, api_estimate: float | None = None) -> None:
        self.entries.append(Entry(label, estimated, api_estimate, billed))

    def summary(self) -> str:
        lines = []
        for e in self.entries:
            api = f", sync estimate ${e.api_estimate:.3f}" if e.api_estimate is not None else ""
            lines.append(f"{e.label}: est ${e.estimated:.3f}{api}, billed ${e.billed:.3f}")
        lines.append(f"total ${self.spent:.3f} / budget ${self.budget:.2f}")
        return "\n".join(lines)
