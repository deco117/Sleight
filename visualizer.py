"""The visualiser - the face of the project.

Renders a dark, cinematic view: an isomorphic keyboard along the bottom, a
living "expression ribbon" rising from every held note that bends with its
per-note pitch bend, shimmers with vibrato and shifts colour with timbre, plus
a luminous hand skeleton and threads tying each tracked finger to the note it
controls.

Three view modes (cycle with 'v'):
    stage  - pure black, graphics only          (best for the demo video)
    ghost  - dim, cool-tinted camera underneath  (best while performing)
    plain  - flat debug HUD (main.py --plain)
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from handtracking import HAND_EDGES

W, H = 1280, 720
KB_TOP = H - 168
KB_BOT = H - 34
KB_MARGIN = 90
RIBBON_H = int(H * 0.52)
BEND_PX = 140.0

WHITE_PC = {0, 2, 4, 5, 7, 9, 11}
WHITE_INDEX = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}   # pitch-class -> white key # in octave
BLACK_ANCHOR = {1: 0, 3: 1, 6: 3, 8: 4, 10: 5}              # pitch-class -> white key it sits after
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(n: int) -> str:
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _scale(col, k):
    """BGR tuple * scalar -> plain-float tuple (OpenCV 5 rejects numpy scalars)."""
    return (float(col[0]) * k, float(col[1]) * k, float(col[2]) * k)


def timbre_color(t: float):
    """t in -1..1  ->  BGR. cool cyan -> cyan-white -> warm magenta/rose."""
    if t <= 0:
        return _lerp((255, 240, 205), (255, 165, 55), -t)      # cyan-white -> bright cyan (BGR)
    return _lerp((255, 240, 205), (190, 70, 255), t)           # cyan-white -> bright magenta/rose (BGR)


class _Backdrop:
    def __init__(self):
        yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        top = np.array([12, 8, 6], np.float32)
        bot = np.array([26, 20, 14], np.float32)
        grad = (top[None, None, :] * (1 - yy[:, :, None]) + bot[None, None, :] * yy[:, :, None])
        canvas = np.repeat(grad, W, axis=1)
        # radial vignette
        xx = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
        yv = np.linspace(-1, 1, H, dtype=np.float32)[:, None]
        r = np.sqrt(xx ** 2 + yv ** 2)
        self.vig = np.clip(1.15 - 0.55 * r ** 1.8, 0.25, 1.0).astype(np.float32)[:, :, None]
        self.base = canvas
        self.grain = (np.random.rand(H, W, 1).astype(np.float32) - 0.5)


class Visualizer:
    def __init__(self, geom, mode: str = "stage", draw_hands: bool = True):
        self.geom = geom
        self.mode = mode
        self.draw_hand_skeleton = draw_hands
        self.bd = _Backdrop()
        self._glide_hist: dict[int, list[float]] = {}
        self._t0 = time.monotonic()
        self._build_key_layout()

    def cycle_mode(self):
        self.mode = {"stage": "ghost", "ghost": "stage"}.get(self.mode, "stage")

    # -- real piano key layout ----------------------------------
    def _build_key_layout(self):
        lo, hi = self.geom.lo, self.geom.hi
        # count white keys spanned
        def white_ordinal(n):
            octs = n // 12
            pc = n % 12
            base = octs * 7
            if pc in WHITE_INDEX:
                return base + WHITE_INDEX[pc]
            return base + WHITE_INDEX[[p for p in (pc - 1, pc + 1) if p in WHITE_INDEX][0]]
        w0 = white_ordinal(lo)
        w1 = white_ordinal(hi)
        n_white = max(1, w1 - w0 + 1)
        self.wkw = (W - 2 * KB_MARGIN) / n_white          # white-key width
        self._x = {}
        for n in range(lo, hi + 1):
            pc = n % 12
            octs = n // 12
            if pc in WHITE_INDEX:
                wi = octs * 7 + WHITE_INDEX[pc] - w0
                self._x[n] = KB_MARGIN + (wi + 0.5) * self.wkw
            else:
                wi = octs * 7 + BLACK_ANCHOR[pc] - w0
                self._x[n] = KB_MARGIN + (wi + 1.0) * self.wkw

    def note_x(self, note) -> float:
        note = int(round(note))
        if note in self._x:
            return self._x[note]
        return KB_MARGIN + (note - self.geom.lo) / self.geom.span * (W - 2 * KB_MARGIN)

    # -- main entry -----------------------------------------------
    def render(self, camera_bgr, engine, tips, hands) -> np.ndarray:
        cv = self.bd.base.copy()

        if self.mode == "ghost" and camera_bgr is not None:
            cam = cv2.resize(camera_bgr, (W, H)).astype(np.float32)
            g = cv2.cvtColor(cam, cv2.COLOR_BGR2GRAY)[:, :, None]
            cam = 0.35 * g + 0.65 * cam                      # mild desaturate
            cam *= np.array([1.12, 0.98, 0.88], np.float32)  # faint cool tint (BGR)
            cv = cv * 0.15 + cam * 0.85                      # camera is the base, graphics on top

        glow = np.zeros((H, W, 3), np.float32)               # additive layer

        self._draw_keyboard(cv, glow, engine)
        self._draw_ribbons(glow, engine)
        if self.draw_hand_skeleton:
            self._draw_hands(glow, hands)
        self._draw_threads(glow, engine, tips)
        self._draw_fingertips(glow, engine, tips)

        # bloom: blur the additive layer and add it back for a soft halo
        small = cv2.resize(glow, (W // 3, H // 3))
        small = cv2.GaussianBlur(small, (0, 0), 5)
        cv = cv + glow + cv2.resize(small, (W, H)) * 0.55

        cv *= self.bd.vig
        cv += self.bd.grain * 4.0
        out = np.clip(cv, 0, 255).astype(np.uint8)

        self._draw_panel(out, engine)
        self._draw_footer(out)
        return out

    # -- layers -------------------------------------------------
    def _draw_keyboard(self, cv, glow, engine):
        active = {b.note: engine.expr.get(b.note) for b in engine.binder.active()}
        n0, n1 = self.geom.lo, self.geom.hi
        ww = self.wkw
        wtop, wbot = int(KB_TOP), int(KB_BOT)
        btop, bbot = int(KB_TOP - 26), int(KB_TOP + (KB_BOT - KB_TOP) * 0.60)

        # white keys first
        for n in range(n0, n1 + 1):
            if (n % 12) not in WHITE_PC:
                continue
            x = self.note_x(n)
            l, r = int(x - ww * 0.46), int(x + ww * 0.46)
            cv2.rectangle(cv, (l, wtop), (r, wbot), (228, 226, 232), -1)
            cv2.rectangle(cv, (l, wtop), (r, wbot), (120, 118, 128), 1, cv2.LINE_AA)
            cv2.rectangle(cv, (l, wtop), (r, wtop + 26), (206, 204, 212), -1)
            if n in active:
                col = timbre_color(active[n].slide if active[n] else 0.0)
                cv2.rectangle(glow, (l, wtop), (r, wbot), _scale(col, 0.7), -1)
                cv2.circle(glow, (int(x), wtop), int(ww * 0.6), _scale(col, 0.3), -1, cv2.LINE_AA)

        # black keys on top
        for n in range(n0, n1 + 1):
            if (n % 12) in WHITE_PC:
                continue
            x = self.note_x(n)
            l, r = int(x - ww * 0.30), int(x + ww * 0.30)
            cv2.rectangle(cv, (l, btop), (r, bbot), (14, 13, 17), -1, cv2.LINE_AA)
            cv2.rectangle(cv, (l, btop), (r, bbot), (40, 38, 46), 1, cv2.LINE_AA)
            cv2.rectangle(cv, (l, btop), (r, btop + 10), (34, 33, 40), -1)
            if n in active:
                col = timbre_color(active[n].slide if active[n] else 0.0)
                cv2.rectangle(glow, (l, btop), (r, bbot), _scale(col, 0.8), -1)
                cv2.circle(glow, (int(x), btop), int(ww * 0.5), _scale(col, 0.3), -1, cv2.LINE_AA)

        cv2.line(cv, (int(KB_MARGIN - 6), wtop - 3), (int(W - KB_MARGIN + 6), wtop - 3),
                 (150, 120, 90), 2, cv2.LINE_AA)

    def _draw_ribbons(self, glow, engine):
        for b in engine.binder.active():
            e = engine.expr.get(b.note)
            if e is None:
                continue
            g = e.glide
            hist = self._glide_hist.setdefault(b.note, [])
            hist.append(g)
            del hist[:-8]
            shimmer = min(1.0, sum(abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))) * 7.0)

            x0 = self.note_x(b.note)
            y0 = int((KB_TOP if (b.note % 12) in WHITE_PC else KB_TOP - 26) - 2)
            y_top = y0 - RIBBON_H
            x_top = x0 + g * BEND_PX
            xc = x0 + g * BEND_PX * 0.45

            ys = np.linspace(0, 1, 48)
            cx = (1 - ys) ** 2 * x0 + 2 * (1 - ys) * ys * xc + ys ** 2 * x_top
            cy = y0 + ys * (y_top - y0)
            half = (5.5 - 3.6 * ys) * (1.0 + 0.3 * abs(g)) + (1.2 if not b.anchored else 0.0)

            col = timbre_color(e.slide)
            base_k = (0.45 + 0.55 * shimmer) if not b.anchored else 1.0

            # render body + halo onto a scratch, then apply a smooth vertical
            # fade so the ribbon dissolves into the dark as it rises
            x_lo = max(0, int(min(cx) - 60)); x_hi = min(W, int(max(cx) + 60))
            y_lo = max(0, y_top - 20); y_hi = min(H, y0 + 4)
            if x_hi <= x_lo or y_hi <= y_lo:
                continue
            scratch = np.zeros((y_hi - y_lo, x_hi - x_lo, 3), np.float32)
            off = np.array([x_lo, y_lo])
            for mult, k in ((2.8, 0.10), (1.15, 0.55), (1.0, 1.05)):
                lft = np.stack([cx - half * mult, cy], 1) - off
                rgt = np.stack([cx + half * mult, cy], 1) - off
                poly = np.concatenate([lft, rgt[::-1]], 0).astype(np.int32)
                cv2.fillPoly(scratch, [poly], _scale(col, k * base_k), cv2.LINE_AA)
            fil = (np.stack([cx, cy], 1) - off).astype(np.int32)
            cv2.polylines(scratch, [fil], False, _scale((255, 255, 255), base_k), 2, cv2.LINE_AA)

            rows = np.linspace(1.0, 0.0, scratch.shape[0], dtype=np.float32) ** 1.15
            scratch *= rows[:, None, None]
            glow[y_lo:y_hi, x_lo:x_hi] += scratch

            cv2.circle(glow, (int(x_top), int(y_top)), int(2 + 4 * abs(g) + 8 * shimmer),
                       _scale(col, 0.95 * base_k), -1, cv2.LINE_AA)

    def _hand_pts(self, hand):
        return [(int(p[0] * W), int(p[1] * H)) for p in hand]

    def _draw_hands(self, glow, hands):
        for hand in hands or []:
            pts = self._hand_pts(hand)
            for a, c in HAND_EDGES:
                cv2.line(glow, pts[a], pts[c], (120, 150, 170), 2, cv2.LINE_AA)
            for (x, y) in pts:
                cv2.circle(glow, (x, y), 2, (150, 180, 200), -1, cv2.LINE_AA)

    def _draw_threads(self, glow, engine, tips):
        px = {t.tid: (int(t.x * W), int(t.y * H)) for t in tips}
        for b in engine.binder.active():
            if not b.anchored or b.tid not in px:
                continue
            x0 = int(self.note_x(b.note))
            y0 = int(KB_TOP if (b.note % 12) in WHITE_PC else KB_TOP - 22)
            e = engine.expr.get(b.note)
            col = _scale(timbre_color(e.slide if e else 0), 0.5)
            cv2.line(glow, px[b.tid], (x0, y0), col, 1, cv2.LINE_AA)

    def _draw_fingertips(self, glow, engine, tips):
        bound = {b.tid for b in engine.binder.active() if b.anchored}
        for t in tips:
            x, y = int(t.x * W), int(t.y * H)
            if t.tid in bound:
                cv2.circle(glow, (x, y), 9, (255, 230, 190), -1, cv2.LINE_AA)
                cv2.circle(glow, (x, y), 4, (255, 255, 255), -1, cv2.LINE_AA)
            else:
                cv2.circle(glow, (x, y), 5, (90, 110, 130), -1, cv2.LINE_AA)

    # -- overlays (crisp, drawn on uint8) ------------------------
    def _draw_panel(self, out, engine):
        pad = 18
        lines = [("SLEIGHT", 0.62, (235, 235, 245)),
                 ("per-note expression  ·  MIDI 2.0 UMP", 0.42, (150, 150, 170))]
        rows = []
        for b in sorted(engine.binder.active(), key=lambda x: x.note):
            e = engine.expr.get(b.note)
            if not e:
                continue
            rows.append((f"{note_name(b.note):<4}  glide {e.glide:+.2f}   "
                        f"slide {e.slide:+.2f}   curl {e.curl:+.2f}",
                         0.44, timbre_color(e.slide)))
        panel_w = 540   # wide enough for "C4   glide +0.00   slide +0.00   curl +0.00"
        h = pad * 2 + 34 + 22 + len(rows) * 22
        panel = out[10:10 + h, 10:10 + panel_w].astype(np.float32)
        panel = panel * 0.35 + np.array([18, 15, 12], np.float32) * 0.65
        out[10:10 + h, 10:10 + panel_w] = np.clip(panel, 0, 255).astype(np.uint8)
        cv2.rectangle(out, (10, 10), (10 + panel_w, 10 + h), (60, 58, 70), 1, cv2.LINE_AA)
        y = 44
        for txt, sc, col in lines:
            cv2.putText(out, txt, (28, y), cv2.FONT_HERSHEY_SIMPLEX, sc, col, 1, cv2.LINE_AA)
            y += 30 if sc > 0.5 else 22
        y += 4
        for txt, sc, col in rows:
            cv2.putText(out, txt, (28, y), cv2.FONT_HERSHEY_SIMPLEX, sc, col, 1, cv2.LINE_AA)
            y += 22

    def _draw_footer(self, out):
        cv2.putText(out, "e synth editor   v view   p preset   r re-calibrate   s settings   u UMP viewer   q quit",
                    (24, H - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 165), 1, cv2.LINE_AA)
        cv2.putText(out, self.mode.upper(), (W - 110, H - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (150, 150, 165), 1, cv2.LINE_AA)
        # credit line - just visible text, not a real link (an OpenCV window
        # can't host a clickable one the way the Settings window can).
        credit = "Dean Coyle Audio - youtube.com/@deancoyle"
        (tw, _), _ = cv2.getTextSize(credit, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
        cv2.putText(out, credit, (W - tw - 20, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 165), 1, cv2.LINE_AA)
