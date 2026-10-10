"""
MIDI 2.0 Universal MIDI Packet builders, plus a text logger.

Every expression update the engine makes gets built as a real UMP message
here. With output_mode = "mpe" (the default) these words only ever reach the
log file, alongside the MPE stream that actually reaches a synth - diff the
two and you can see MPE is the lossy part: 32-bit per-note pitch bend,
registered per-note controllers, poly pressure, none of which MPE can carry.
With output_mode = "midi2_ump" these same words (built right here, nothing
duplicated) also go out live over a real Windows MIDI Services endpoint - see
midi2_output.py for how, and why that needed a companion .NET process rather
than a plain Python import.

Spec: MIDI 2.0 UMP 1.1, Message Type 0x4 (MIDI 2.0 Channel Voice) - two 32-bit
words per message. word0 is [type|group|status|channel|byte2|byte3], word1 is
the payload (a 16- or 32-bit value depending on the message).
"""
from __future__ import annotations

import datetime
import pathlib

CENTER_32 = 0x80000000  # pitch-bend / bipolar-controller centre value


def _word0(group: int, status: int, channel: int, byte2: int, byte3: int) -> int:
    return (
        (0x4 << 28)
        | ((group & 0xF) << 24)
        | ((status & 0xF) << 20)
        | ((channel & 0xF) << 16)
        | ((byte2 & 0xFF) << 8)
        | (byte3 & 0xFF)
    )


def note_on(group: int, channel: int, note: int, velocity16: int,
            attr_type: int = 0, attr: int = 0) -> tuple[int, int]:
    return _word0(group, 0x9, channel, note, attr_type), ((velocity16 & 0xFFFF) << 16) | (attr & 0xFFFF)


def note_off(group: int, channel: int, note: int, velocity16: int = 0) -> tuple[int, int]:
    return _word0(group, 0x8, channel, note, 0), (velocity16 & 0xFFFF) << 16


def per_note_pitch_bend(group: int, channel: int, note: int, value32: int) -> tuple[int, int]:
    """status 0x6 - full 32-bit per-note pitch bend, centre = 0x80000000."""
    return _word0(group, 0x6, channel, note, 0), value32 & 0xFFFFFFFF


def per_note_controller(group: int, channel: int, note: int, index: int, value32: int) -> tuple[int, int]:
    """status 0x0 - Registered Per-Note Controller. index 74 == timbre/brightness."""
    return _word0(group, 0x0, channel, note, index), value32 & 0xFFFFFFFF


def per_note_pressure(group: int, channel: int, note: int, value32: int) -> tuple[int, int]:
    """status 0xA - Poly Pressure, 32-bit in MIDI 2.0."""
    return _word0(group, 0xA, channel, note, 0), value32 & 0xFFFFFFFF


def bipolar_to_u32(x: float) -> int:
    """-1..+1  ->  full 32-bit range centred on 0x80000000."""
    x = max(-1.0, min(1.0, x))
    if x >= 0:
        return min(0xFFFFFFFF, CENTER_32 + int(x * (0xFFFFFFFF - CENTER_32)))
    return max(0, CENTER_32 + int(x * CENTER_32))


def unipolar_to_u32(x: float) -> int:
    x = max(0.0, min(1.0, x))
    return int(x * 0xFFFFFFFF)


class UmpLogger:
    def __init__(self, path: str | pathlib.Path, group: int = 0):
        self.path = pathlib.Path(path)
        self.group = group
        self._f = None

    def open(self):
        self._f = self.path.open("w", encoding="utf-8")
        self._f.write("# MIDI 2.0 UMP session log - Expressive MIDI 2.0 Keyboard\n")
        self._f.write("# columns: wall-clock | UMP words (hex) | human-readable\n\n")

    def log(self, words: tuple[int, int], human: str):
        if not self._f:
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        hexwords = " ".join(f"{w:08X}" for w in words)
        self._f.write(f"{ts}  {hexwords}  ; {human}\n")
        self._f.flush()   # a live viewer tails this file - buffered writes would sit unseen

    def close(self):
        if self._f:
            self._f.close()
            self._f = None
