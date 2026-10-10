"""Maps MIDI note numbers to a normalised position along the keyboard.

u = 0.0 at the lowest key, 1.0 at the highest key. This is deliberately a
straight linear map across the whole span - it ignores the white/black key
offset, which is well within the tolerance the fingertip binder needs (it
only has to pick the *nearest* finger to a pressed key, and fingers are
~7 keys apart at worst).
"""
from __future__ import annotations


class KeyboardGeometry:
    def __init__(self, lowest_note: int, highest_note: int):
        assert highest_note > lowest_note
        self.lo = lowest_note
        self.hi = highest_note
        self.span = highest_note - lowest_note

    def note_to_u(self, note: int) -> float:
        return (note - self.lo) / self.span

    def u_to_note(self, u: float) -> int:
        return int(round(self.lo + u * self.span))

    def semitone_width_u(self) -> float:
        """How wide one semitone is in u units - used for match tolerances."""
        return 1.0 / self.span
