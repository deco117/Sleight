"""
Fingertip drift -> smoothed, scaled -1..1 expression values.

The three axes borrow the Seaboard's names for the dimensions of touch:

  glide  finger slides sideways on the key   (Seaboard: pitch axis)
         a slow slide bends the note; a fast back-and-forth is vibrato.
         Per-note vibrato on one voice of a held chord is the whole point
         of this project - a normal keyboard can't do it.
  slide  finger slides toward / away from the fallboard   (Seaboard: Y / timbre)
  curl   finger curls or flattens while it holds the key

Everything is measured relative to where the finger was at note-on, so the
values are drift, not absolute position. mpe_output then routes each axis to
whatever the gesture_map says (per-note bend, or a CC you MIDI-learn).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


class OnePole:
    """Dead-simple one-pole low-pass. tau_ms is the time constant - bigger is
    smoother and laggier. First sample passes straight through so a note
    doesn't glide up from zero when it starts."""

    def __init__(self, tau_ms: float):
        self.tau = max(1e-3, tau_ms / 1000.0)
        self.y = 0.0
        self._primed = False

    def step(self, x: float, dt: float) -> float:
        if not self._primed:
            self.y = x
            self._primed = True
            return x
        a = dt / (self.tau + dt)          # dt-aware, so frame-rate wobble is fine
        self.y += a * (x - self.y)
        return self.y

    def reset(self, value: float = 0.0):
        self.y = value
        self._primed = False


@dataclass
class ExpressionConfig:
    glide_full_scale: float      # sideways drift that maps to a full-scale value
    slide_full_scale: float      # forward/back drift for full scale
    glide_deadzone: float        # ignore sideways drift smaller than this (jitter)
    smoothing_ms: float
    invert_glide: bool = False
    invert_slide: bool = False
    curl_full_scale: float = 0.35
    invert_curl: bool = False


class NoteExpression:
    """One of these per sounding note. Feed it the binding's drift every frame,
    read back .glide / .slide / .curl (each -1..1)."""

    def __init__(self, cfg: ExpressionConfig):
        self.cfg = cfg
        self._glide_lp = OnePole(cfg.smoothing_ms)
        self._slide_lp = OnePole(cfg.smoothing_ms)
        self._curl_lp = OnePole(cfg.smoothing_ms)
        self.glide = 0.0
        self.slide = 0.0
        self.curl = 0.0

    def update(self, du: float, dv: float, dcurl: float, dt: float):
        # glide: subtract the deadzone rather than just gating on it, so you
        # don't get a jump from 0 to (deadzone/full_scale) the moment you cross it
        g = du
        if abs(g) < self.cfg.glide_deadzone:
            g = 0.0
        else:
            g -= math.copysign(self.cfg.glide_deadzone, g)
        g /= self.cfg.glide_full_scale
        if self.cfg.invert_glide:
            g = -g

        s = dv / self.cfg.slide_full_scale
        if self.cfg.invert_slide:
            s = -s

        c = dcurl / self.cfg.curl_full_scale
        if self.cfg.invert_curl:
            c = -c

        self.glide = _clip(self._glide_lp.step(g, dt))
        self.slide = _clip(self._slide_lp.step(s, dt))
        self.curl = _clip(self._curl_lp.step(c, dt))
        return self.glide, self.slide, self.curl


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))
