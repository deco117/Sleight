"""
Four clicks on the corners of the key bed -> a homography that maps camera
pixels to keyboard position. That's what lets the camera sit at any angle:
the perspective is baked into H.

Keyboard space:
    u : 0.0 lowest key .. 1.0 highest key   (along the keyboard)
    v : 0.0 far edge   .. 1.0 near edge      (key depth, toward you)

Click order: far-low, far-high, near-high, near-low - i.e. clockwise from
top-left as you see it with the camera above and the mirror view on. It has
to match DST below.
"""
from __future__ import annotations

import json
import pathlib

import cv2
import numpy as np

DST = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
CLICK_LABELS = ["far / lowest key", "far / highest key", "near / highest key", "near / lowest key"]


class Calibration:
    def __init__(self, H: np.ndarray, frame_size: tuple[int, int]):
        self.H = H
        self.frame_size = frame_size

    def image_to_keyboard(self, pts_xy_norm: np.ndarray) -> np.ndarray:
        """pts in normalised image coords (0..1). Returns (u,v) array."""
        w, h = self.frame_size
        px = np.asarray(pts_xy_norm, dtype=np.float32).reshape(-1, 1, 2).copy()
        px[:, 0, 0] *= w
        px[:, 0, 1] *= h
        out = cv2.perspectiveTransform(px, self.H)
        return out.reshape(-1, 2)

    def save(self, path: str | pathlib.Path):
        pathlib.Path(path).write_text(json.dumps({
            "H": self.H.tolist(),
            "frame_size": list(self.frame_size),
        }, indent=2))

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Calibration":
        d = json.loads(pathlib.Path(path).read_text())
        return cls(np.array(d["H"], dtype=np.float32), tuple(d["frame_size"]))


def run_calibration(cap, out_path: str | pathlib.Path, flip: bool = True) -> Calibration | None:
    """Returns None if the user cancelled (Esc, or closed the window) instead
    of clicking all 4 corners - callers should keep whatever calibration they
    already had rather than treating that as success."""
    pts: list[tuple[int, int]] = []
    win = "Calibrate - click 4 corners (far-low, far-high, near-high, near-low). u=undo, ENTER=accept"

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.moveWindow(win, 40, 40)          # OpenCV can restore an off-screen position
    cv2.setMouseCallback(win, on_mouse)

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        if flip:
            frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        disp = frame.copy()
        for i, p in enumerate(pts):
            cv2.circle(disp, p, 6, (0, 255, 0), -1)
            cv2.putText(disp, f"{i+1}", (p[0] + 8, p[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        if len(pts) >= 2:
            cv2.polylines(disp, [np.array(pts, np.int32)], len(pts) == 4, (0, 200, 255), 1)
        msg = "done - press ENTER" if len(pts) == 4 else f"click: {CLICK_LABELS[len(pts)]}"
        cv2.putText(disp, msg, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow(win, disp)
        if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
            return None    # closed via the window's X - cancel, don't just reopen it
        k = cv2.waitKey(1) & 0xFF
        if k in (ord('u'), 8) and pts:
            pts.pop()
        elif k in (13, 10) and len(pts) == 4:
            break
        elif k == 27:
            cv2.destroyWindow(win)
            return None    # Esc - cancel. Caller keeps whatever calibration it already had.

    cv2.destroyWindow(win)
    H = cv2.getPerspectiveTransform(np.float32(pts), DST)
    calib = Calibration(H, (w, h))
    calib.save(out_path)
    return calib
