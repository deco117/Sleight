"""
Camera reader on its own thread, always handing back the newest frame.

cv2.VideoCapture buffers frames in a FIFO. Call read() from a loop that's even
a hair slower than the camera and you fall behind by several frames - 100-300ms
of lag, and the expression feels like it's lagging your fingers. So a thread
grabs flat out and keeps only the latest frame; read() just copies that.
CAP_PROP_BUFFERSIZE=1 helps too where the backend honours it.
"""
from __future__ import annotations

import sys
import threading
import time

import cv2


class Camera:
    def __init__(self, index: int, width: int, height: int, backend: int | None = None):
        if backend is None:
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else 0
        self.cap = cv2.VideoCapture(index, backend)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not self.cap.isOpened():
            # Deliberately NOT SystemExit: this constructor can run deep
            # inside a Tkinter button callback (the Settings window's
            # camera buttons), and Tkinter's callback wrapper re-raises
            # SystemExit instead of routing it through the normal
            # report_callback_exception path - it would take the whole
            # app down instead of just failing this one action. An
            # ordinary exception is catchable everywhere that matters.
            raise RuntimeError(f"Cannot open camera index {index}")
        self._frame = None
        self._lock = threading.Lock()
        self._run = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        # wait for first frame
        for _ in range(100):
            if self._frame is not None:
                break
            time.sleep(0.02)

    def _loop(self):
        while self._run:
            ok, f = self.cap.read()
            if ok:
                with self._lock:
                    self._frame = f
            else:
                time.sleep(0.005)

    def read(self):
        with self._lock:
            return (self._frame is not None,
                    None if self._frame is None else self._frame.copy())

    def release(self):
        self._run = False
        self._t.join(timeout=0.5)
        self.cap.release()
