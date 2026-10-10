"""
MPE output. One MPE member channel per sounding note, so every note carries
its own pitch bend and CCs - that's what makes the per-note expression land
in a synth that only speaks MIDI 1.0.

Lower Zone layout: master = channel 1 (0-based 0), members = channels 2..16.

This is the default output_mode ("mpe") because it needs nothing beyond a
virtual MIDI port (loopMIDI) and every DAW/synth already understands it. A
genuine MIDI 2.0 UMP path also exists now - output_mode = "midi2_ump", see
midi2_output.py - for anyone with Windows MIDI Services' App SDK installed;
that path reuses the same UMP words this module's sibling, ump.py, builds and
logs, and sends them live instead of just to a file. Until you opt into that
mode, MPE (translated from the same per-note expression data) is what
actually reaches a synth.
"""
from __future__ import annotations

import rtmidi

# what each finger axis does if config doesn't say
DEFAULT_GESTURE_MAP = {
    "glide": {"target": "pitchbend"},
    "slide": {"target": "cc", "cc": 74},
    "curl":  {"target": "cc", "cc": 1},
}

_LOOPMIDI_URL = "https://www.tobias-erichsen.de/software/loopmidi.html"


def _find_port(midi: rtmidi.MidiOut, match: str):
    """Return (index, all_names). index is the first port containing `match`
    (case-insensitive), or 0 if `match` is empty, or None if nothing matches."""
    names = midi.get_ports()
    if not names:
        return None, names
    if not match:
        return 0, names
    for i, n in enumerate(names):
        if match.lower() in n.lower():
            return i, names
    return None, names


class MpeOutput:
    def __init__(self, port_match: str, master_channel: int = 1,
                 member_channels: int = 15, bend_range: int = 48,
                 dry_run: bool = False, gesture_map: dict | None = None):
        self.master = master_channel - 1          # to 0-based
        self.members = list(range(self.master + 1, self.master + 1 + member_channels))
        self.bend_range = bend_range
        self.dry_run = dry_run
        self.gesture_map = gesture_map or DEFAULT_GESTURE_MAP

        self._note_to_ch: dict[int, int] = {}
        self._busy = {c: False for c in self.members}
        self._rr = 0                              # round-robin cursor for _alloc

        self.midi = rtmidi.MidiOut()
        idx, names = _find_port(self.midi, port_match)
        self.port_names = names
        self.opened = False
        self.open_name = None

        if dry_run:
            return
        if idx is not None:
            self.midi.open_port(idx)
            self.opened = True
            self.open_name = names[idx]
            return

        # No matching port. open_virtual_port works on macOS/Linux; on Windows
        # rtmidi can't make one, so tell the user how to.
        try:
            self.midi.open_virtual_port(port_match or "Sleight")
            self.opened = True
            self.open_name = f"{port_match or 'Sleight'} (virtual)"
        except Exception:
            print(f"  ! No MIDI-out port named '{port_match}'.\n"
                  f"    Windows needs a virtual one: install loopMIDI ({_LOOPMIDI_URL}),\n"
                  f"    open it, type '{port_match}', click +, then restart Sleight.\n"
                  f"    Ports seen now: {names or '(none)'}")

    # ---- raw MIDI ------------------------------------------------------
    def _send(self, *data: int):
        if self.opened:
            self.midi.send_message(list(data))

    def _cc(self, ch: int, num: int, val: int):
        self._send(0xB0 | (ch & 0xF), num & 0x7F, val & 0x7F)

    def _pitchbend(self, ch: int, value14: int):
        value14 = max(0, min(16383, int(value14)))
        self._send(0xE0 | (ch & 0xF), value14 & 0x7F, (value14 >> 7) & 0x7F)

    def _rpn(self, ch: int, msb: int, lsb: int, value_msb: int, value_lsb: int = 0):
        # RPN = select with CC 101/100, set with CC 6/38, then null-select so a
        # later stray CC 6 doesn't land on this RPN.
        self._cc(ch, 101, msb)
        self._cc(ch, 100, lsb)
        self._cc(ch, 6, value_msb)
        self._cc(ch, 38, value_lsb)
        self._cc(ch, 101, 127)
        self._cc(ch, 100, 127)

    # ---- setup ------------------------------------------------------
    def configure_zone(self):
        # RPN 0x0006 on the master = "MPE Configuration Message", value is how
        # many member channels this zone owns.
        self._rpn(self.master, 0x00, 0x06, len(self.members))
        # RPN 0x0000 = pitch-bend range. Set it wide on every channel and centre
        # everything so we start from a known state.
        for ch in [self.master, *self.members]:
            self._rpn(ch, 0x00, 0x00, self.bend_range, 0)
            self._pitchbend(ch, 8192)
            self._cc(ch, 74, 64)

    # ---- notes ------------------------------------------------------
    def _alloc(self) -> int:
        """Pick a free member channel, round-robin. If every channel is live
        (more than `member_channels` notes at once) steal the next one - the
        oldest-ish note loses its independence, which beats dropping a note."""
        for _ in range(len(self.members)):
            ch = self.members[self._rr % len(self.members)]
            self._rr += 1
            if not self._busy[ch]:
                self._busy[ch] = True
                return ch
        ch = self.members[self._rr % len(self.members)]
        self._rr += 1
        return ch

    def note_on(self, note: int, velocity: int) -> int:
        ch = self._alloc()
        self._note_to_ch[note] = ch
        # reset this channel's expression before the note starts
        self._pitchbend(ch, 8192)
        self._cc(ch, 74, 64)
        self._send(0xD0 | (ch & 0xF), 0)
        self._send(0x90 | (ch & 0xF), note & 0x7F, max(1, velocity) & 0x7F)
        return ch

    def note_off(self, note: int):
        ch = self._note_to_ch.pop(note, None)
        if ch is None:
            return
        self._send(0x80 | (ch & 0xF), note & 0x7F, 0)
        self._pitchbend(ch, 8192)
        self._busy[ch] = False

    def channel_for(self, note: int):
        return self._note_to_ch.get(note)

    # ---- expression ----------------------------------------------
    def set_expression(self, note: int, axis: str, bipolar: float):
        """Send one finger axis for one note, routed per the gesture_map:
        per-note pitch bend, or a CC on the note's member channel."""
        spec = self.gesture_map.get(axis)
        ch = self._note_to_ch.get(note)
        if not spec or ch is None:
            return
        v = max(-1.0, min(1.0, bipolar))
        target = spec.get("target", "none")
        if target == "pitchbend":
            self._pitchbend(ch, 8192 + v * 8191)
        elif target == "cc":
            self._cc(ch, int(spec.get("cc", 74)), round(64 + v * 63))

    def passthrough(self, status: int, d1: int, d2: int):
        """Anything the keyboard sends that isn't a note - sustain pedal, mod
        wheel, its own aftertouch - goes straight out on the master channel."""
        self._send((status & 0xF0) | (self.master & 0xF), d1, d2)

    def all_notes_off(self):
        for ch in [self.master, *self.members]:
            self._cc(ch, 123, 0)
            self._pitchbend(ch, 8192)

    # patch / editor controls only mean something for the in-process synths
    def next_patch(self): pass
    def prev_patch(self): pass
    def current_patch_name(self): return ""
    def show_editor(self): pass

    def close(self):
        try:
            self.all_notes_off()
        finally:
            self.midi.close_port()
