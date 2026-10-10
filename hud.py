"""
The plain debug overlay (main.py --plain). Draws straight onto the camera
frame: fingertip dots, and a strip along the bottom showing every held note
with its three expression bars. visualizer.py is the pretty version; this one
is for seeing what the tracker and binder actually think is going on.
"""
from __future__ import annotations

import cv2

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_GLIDE_COL = (255, 120, 0)     # BGR - orange
_SLIDE_COL = (0, 160, 255)     # blue
_CURL_COL = (180, 100, 255)    # purple


def draw_hud(frame, engine, tips, tips_kb):
    h, w = frame.shape[:2]

    for t in tips:
        cv2.circle(frame, (int(t.x * w), int(t.y * h)), 5, (0, 220, 255), -1)
    tip_px = {t.tid: (int(t.x * w), int(t.y * h)) for t in tips}

    strip_y = h - 40
    cv2.rectangle(frame, (0, strip_y), (w, h), (30, 30, 30), -1)

    for b in engine.binder.active():
        px = int(engine.geom.note_to_u(b.note) * w)
        col = (0, 255, 120) if b.anchored else (120, 120, 120)
        cv2.line(frame, (px, strip_y), (px, h), col, 3)

        e = engine.expr.get(b.note)
        if e:
            for i, (val, c) in enumerate(((e.glide, _GLIDE_COL),
                                          (e.slide, _SLIDE_COL),
                                          (e.curl, _CURL_COL))):
                y = strip_y - 2 - i * 6
                cv2.line(frame, (px, y), (px + int(val * 60), y), c, 3)
            cv2.putText(frame, f"{b.note} {e.glide:+.2f}/{e.slide:+.2f}/{e.curl:+.2f}",
                        (max(0, px - 40), strip_y - 20), _FONT, 0.4, col, 1)

        # line from the finger to the key it's bound to
        if b.anchored and b.tid in tip_px:
            cv2.line(frame, tip_px[b.tid], (px, strip_y), col, 1)

    xc = engine.expr_cfg
    cv2.putText(frame,
                f"notes:{len(engine.binder.active())}  "
                f"glideFS:{xc.glide_full_scale:.3f}  slideFS:{xc.slide_full_scale:.2f}",
                (12, 24), _FONT, 0.6, (255, 255, 255), 2)
    cv2.putText(frame,
                "orange=glide  blue=slide  purple=curl    q quit  r recal  s settings  u UMP",
                (12, h - 50), _FONT, 0.5, (200, 200, 200), 1)
