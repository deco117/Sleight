"""
Hand tracking, built on MediaPipe's HandLandmarker (the Tasks API - the old
mp.solutions.hands is gone in mediapipe 1.x).

Two jobs:
  1. per frame, pull the five fingertip points out of each detected hand, in
     normalised image coords (0..1, origin top-left), plus a curl value per
     finger.
  2. give each fingertip a stable id that survives across frames, so a note
     can stay bound to "the finger that played it".

We do NOT use MediaPipe's handedness (left/right) or its own tracking. From a
camera looking straight down at a keyboard it gets left/right wrong constantly
- the hands are rotated ~90 degrees from how the model expects to see them.
The nearest-neighbour tracker below is dumb but it doesn't care about any of
that.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
except Exception as e:  # pragma: no cover
    raise SystemExit(f"mediapipe import failed: {e}")

from config import HERE as _APP_DIR

# MediaPipe's 21-landmark hand model. Tips are 4/8/12/16/20.
FINGERTIP_LANDMARKS = [4, 8, 12, 16, 20]
FINGER_NAMES = {4: "T", 8: "I", 12: "M", 16: "R", 20: "P"}

# the four joints down each finger, knuckle to tip (MCP, PIP, DIP, TIP).
FINGER_CHAINS = {4: (1, 2, 3, 4), 8: (5, 6, 7, 8), 12: (9, 10, 11, 12),
                 16: (13, 14, 15, 16), 20: (17, 18, 19, 20)}

# skeleton edges, only used by the visualiser to draw the hand
HAND_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]
DEFAULT_MODEL = _APP_DIR / "hand_landmarker.task"


def _finger_curl(lms, chain) -> float:
    """How bent the finger is: 0 straight, ~1 curled into a fist.

    Trick: measure the straight-line distance knuckle->tip and divide by the
    length you get walking joint to joint. Straight finger, those are equal.
    Curl it and the straight-line span collapses while the path length stays
    put, so the ratio drops. 1 - ratio is the curl.

    The /0.7 is because a comfortable full curl only gets the ratio down to
    about 0.3, not 0 - this stretches that range back out to 0..1. Uses the
    3D points; z is only relative depth from MediaPipe but it's enough here.
    """
    p = [np.array([lms[i].x, lms[i].y, lms[i].z]) for i in chain]
    path = sum(float(np.linalg.norm(p[i + 1] - p[i])) for i in range(3))
    if path < 1e-6:
        return 0.0
    span = float(np.linalg.norm(p[3] - p[0]))
    return max(0.0, min(1.0, (1.0 - span / path) / 0.7))


@dataclass
class Fingertip:
    x: float           # normalised image coords, 0..1
    y: float
    z: float           # relative depth, smaller = nearer the camera
    hand: int          # which detected hand it came from, 0 or 1
    landmark: int      # 4/8/12/16/20
    tid: int = -1      # stable id, set by FingertipTracker
    curl: float = 0.0  # this finger's curl, 0..1


class HandTracker:
    """Thin wrapper round HandLandmarker. One instance, call process() per frame."""

    def __init__(self, model_path: str | pathlib.Path = DEFAULT_MODEL,
                 num_hands: int = 2, min_det: float = 0.6, min_track: float = 0.5):
        opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_det,
            min_tracking_confidence=min_track,
        )
        self._lm = vision.HandLandmarker.create_from_options(opts)
        self._last_ts = -1
        # full 21-pt skeletons from the last frame, for the visualiser only
        self.last_hands: list[list[tuple[float, float, float]]] = []

    def process(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[Fingertip]:
        # detect_for_video throws if timestamps aren't strictly increasing, and
        # two frames can land on the same millisecond. Just bump it.
        if timestamp_ms <= self._last_ts:
            timestamp_ms = self._last_ts + 1
        self._last_ts = timestamp_ms

        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=np.ascontiguousarray(rgb_frame))
        res = self._lm.detect_for_video(image, timestamp_ms)

        tips: list[Fingertip] = []
        self.last_hands = []
        if not res.hand_landmarks:
            return tips

        for hand_idx, lms in enumerate(res.hand_landmarks):
            self.last_hands.append([(p.x, p.y, p.z) for p in lms])
            for li in FINGERTIP_LANDMARKS:
                p = lms[li]
                tips.append(Fingertip(p.x, p.y, p.z, hand_idx, li,
                                      curl=_finger_curl(lms, FINGER_CHAINS[li])))
        return tips

    def close(self):
        self._lm.close()


class FingertipTracker:
    """Keeps fingertip ids stable frame to frame.

    Pure nearest-neighbour: each existing track grabs the closest detection it
    can find within max_match_dist. Anything left over starts a new track.
    A track that goes unmatched for max_missing frames is dropped.

    Good enough because fingers on a keyboard don't move far between frames
    and rarely cross. When two do cross the ids can swap - you hear it as a
    momentary wrong bend on one note, then it settles.
    """

    def __init__(self, max_match_dist: float = 0.06, max_missing: int = 6):
        self.max_match_dist = max_match_dist
        self.max_missing = max_missing
        self._tracks: dict[int, dict] = {}     # tid -> {x, y, z, landmark, missing}
        self._next = 1

    def update(self, tips: list[Fingertip]) -> list[Fingertip]:
        used = set()

        for tid, tr in list(self._tracks.items()):
            best, best_d = None, 1e9
            for i, t in enumerate(tips):
                if i in used:
                    continue
                d = ((t.x - tr["x"]) ** 2 + (t.y - tr["y"]) ** 2) ** 0.5
                # nudge against matching a different finger to this track -
                # cheap way to keep index/middle from trading ids when close
                if t.landmark != tr["landmark"]:
                    d += 0.02
                if d < best_d:
                    best, best_d = i, d

            if best is not None and best_d <= self.max_match_dist:
                t = tips[best]
                used.add(best)
                t.tid = tid
                tr.update(x=t.x, y=t.y, z=t.z, landmark=t.landmark, missing=0)
            else:
                tr["missing"] += 1
                if tr["missing"] > self.max_missing:
                    del self._tracks[tid]

        for i, t in enumerate(tips):
            if i in used:
                continue
            t.tid = self._next
            self._tracks[self._next] = dict(x=t.x, y=t.y, z=t.z,
                                            landmark=t.landmark, missing=0)
            self._next += 1

        return [t for t in tips if t.tid != -1]

    def get(self, tid: int):
        return self._tracks.get(tid)
