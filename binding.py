"""
Match each key that gets pressed to the fingertip that's holding it, then
watch how that fingertip moves. Everything downstream (pitch bend, timbre,
curl) is just that displacement, smoothed and scaled.

Why this is even tractable: the finger doesn't leave the key while the note
sounds. It stays within a semitone or so of where the key sits in the
calibrated frame, so "which finger played this note" collapses to "closest
fingertip to the key", and expression is "how far has that fingertip drifted
since note-on". No gesture recognition, no ML on top of the tracker.

Coordinates are keyboard space from calibration.py:
  u  = along the keyboard, 0..1 low to high   (finger slides sideways -> du)
  v  = across the key,      0 far edge .. 1 near edge  (slides in/out -> dv)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Binding:
    note: int
    channel: int
    tid: int                 # fingertip track id from handtracking; -1 = no finger
    u0: float                # where the finger was, in keyboard space, at note-on
    v0: float
    du: float = 0.0          # current drift from (u0, v0)
    dv: float = 0.0
    curl0: float = 0.0       # finger curl at note-on (0 straight .. 1 curled)
    dcurl: float = 0.0       # current curl minus curl0
    last_seen: float = field(default_factory=time.monotonic)
    anchored: bool = True    # False = playing but no finger to track yet
    finger_label: str = "?"  # T/I/M/R/P, just for the HUD


class Binder:
    # 3 semitones of slop when deciding a fingertip belongs to a key. Tighter
    # than this and a slightly-off calibration keeps losing the anchor;
    # looser and a neighbouring finger can steal the note.
    def __init__(self, geom, match_tolerance_semitones: float = 3.0):
        self.geom = geom
        self.tol_u = match_tolerance_semitones * geom.semitone_width_u()
        self.bindings: dict[int, Binding] = {}      # note -> Binding

    def note_on(self, note: int, channel: int,
                tips_kb: list[tuple[int, float, float, str]],
                curl_by_tid: dict[int, float] | None = None) -> Binding:
        """tips_kb: (tid, u, v, finger_label) for every visible fingertip,
        already mapped into keyboard space."""
        curl_by_tid = curl_by_tid or {}
        target_u = self.geom.note_to_u(note)

        # a fingertip can only hold one note at a time
        taken = {b.tid for b in self.bindings.values() if b.anchored}

        # nearest tip to the key. distance is mostly along the keyboard (u);
        # the small v term just breaks ties toward a finger sitting mid-key
        # rather than one reaching in from the front edge.
        best, best_d = None, 1e9
        for tid, u, v, label in tips_kb:
            if tid in taken:
                continue
            if not (-0.15 <= v <= 1.25):           # not over the keys at all
                continue
            d = abs(u - target_u) + 0.25 * abs(v - 0.5)
            if d < best_d:
                best, best_d = (tid, u, v, label), d

        if best is not None and abs(best[1] - target_u) <= self.tol_u:
            tid, u, v, label = best
            b = Binding(note, channel, tid, u, v, finger_label=label,
                        curl0=curl_by_tid.get(tid, 0.0))
        else:
            # nothing close enough - hand's occluded, or it was a fast run and
            # the tracker hasn't caught up. Note still sounds; it just has no
            # expression until update() finds a finger for it. In practice
            # that mostly doesn't happen, so re-anchoring later isn't worth it.
            b = Binding(note, channel, -1, target_u, 0.5,
                        anchored=False, finger_label="-")

        self.bindings[note] = b
        return b

    def note_off(self, note: int):
        self.bindings.pop(note, None)

    def update(self, tips_by_tid: dict[int, tuple[float, float, str]],
               curl_by_tid: dict[int, float] | None = None):
        """Called every frame. Refresh the drift for every anchored note."""
        now = time.monotonic()
        for b in self.bindings.values():
            if not b.anchored:
                continue
            cur = tips_by_tid.get(b.tid)
            if cur is None:
                # finger dropped out for a frame or two. Hold the last values -
                # snapping du/dv/dcurl to zero here is an audible glitch.
                continue
            u, v, label = cur
            b.du = u - b.u0
            b.dv = v - b.v0
            if curl_by_tid is not None and b.tid in curl_by_tid:
                b.dcurl = curl_by_tid[b.tid] - b.curl0
            b.finger_label = label
            b.last_seen = now

    def active(self):
        return list(self.bindings.values())
