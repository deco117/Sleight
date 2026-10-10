"""
The engine. One Engine owns the whole pipeline for a session:

    camera frame
      -> HandTracker + FingertipTracker      (fingertips with stable ids)
      -> calibration                          (into keyboard space)
      -> Binder                               (which finger holds which note)
      -> NoteExpression per note              (drift -> smoothed -1..1)
      -> output (MpeOutput / Midi2Ump / VstHost / Surge) (per-note bend + CCs)
      -> UmpLogger                            (the MIDI 2.0 words, to a file)

MIDI notes come in on a background rtmidi callback and are drained once per
frame in step(). Everything else is single-threaded in the caller's loop.
"""
from __future__ import annotations

import collections
import time

import cv2
import numpy as np

import ump
from binding import Binder
from calibration import Calibration
from config import Config, CALIBRATION_PATH
from expression import ExpressionConfig, NoteExpression
from handtracking import FINGER_NAMES, FingertipTracker, HandTracker
from keyboard_geom import KeyboardGeometry
from midi2_output import Midi2UmpOutput
from mpe_output import MpeOutput
from osc_output import SurgeOscOutput
from vst_output import VstHostOutput

# UMP registered per-note controller numbers we log the axes under
_CC_SLIDE = 74
_CC_CURL = 1


def _make_output(cfg: Config, dry_run: bool):
    """Build whichever output the config asks for. All of these expose the
    same handful of methods (note_on/off, set_expression, passthrough,
    close, ...)."""
    gmap = cfg.gesture_map
    if cfg.output_mode == "midi2_ump":
        # Live MIDI 2.0 UMP over a real Windows MIDI Services endpoint - see
        # midi2_output.py for why this needs a companion .NET bridge process
        # rather than a plain Python import. Importing Midi2UmpOutput at the
        # top of this file is always safe on any machine (it does no WinRT
        # work at import time); the bridge process only gets launched here,
        # inside its __init__, and only because this branch was selected.
        return Midi2UmpOutput(cfg.midi_out_match, cfg.ump_group,
                              dry_run=dry_run, gesture_map=gmap,
                              bridge_exe=cfg.midi2_bridge_exe or None)
    if cfg.output_mode == "vst_host":
        return VstHostOutput(
            plugin_path=cfg.vst_plugin_path, preset_dir=cfg.vst_preset_dir,
            start_preset=cfg.vst_start_preset,
            bend_semitones=cfg.per_note_pitch_bend_range,
            sample_rate=cfg.vst_sample_rate, block_size=cfg.vst_block_size,
            audio_device=cfg.audio_output_device, app_dir=CALIBRATION_PATH.parent,
            dry_run=dry_run, gesture_map=gmap)
    if cfg.output_mode == "surge_osc":
        patch_dir = (str(CALIBRATION_PATH.parent / cfg.surge_patch_dir)
                     if cfg.surge_patch_dir else "")
        return SurgeOscOutput(
            cfg.surge_osc_host, cfg.surge_osc_port, cfg.surge_bend_semitones,
            cfg.resolved_surge_cli(), auto_start=cfg.surge_auto_start, dry_run=dry_run,
            audio_interface=cfg.surge_audio_interface, buffer_size=cfg.surge_buffer_size,
            sample_rate=cfg.surge_sample_rate, patch_dir=patch_dir,
            start_patch=cfg.surge_start_patch, gesture_map=gmap)
    return MpeOutput(cfg.midi_out_match, cfg.mpe_master_channel,
                     cfg.mpe_member_channels, cfg.per_note_pitch_bend_range,
                     dry_run=dry_run, gesture_map=gmap)


class Engine:
    def __init__(self, cfg: Config, calib: Calibration, dry_run: bool = False):
        self.cfg = cfg
        self.calib = calib
        self.geom = KeyboardGeometry(cfg.lowest_note, cfg.highest_note)

        self.tracker = HandTracker(num_hands=cfg.max_hands,
                                   min_det=cfg.min_detection_confidence,
                                   min_track=cfg.min_tracking_confidence)
        self.ftrack = FingertipTracker()
        self.binder = Binder(self.geom)

        self.expr_cfg = ExpressionConfig(
            glide_full_scale=cfg.glide_full_scale,
            slide_full_scale=cfg.slide_full_scale,
            glide_deadzone=cfg.glide_deadzone,
            smoothing_ms=cfg.smoothing_ms,
            invert_glide=cfg.invert_glide,
            invert_slide=cfg.invert_slide,
            curl_full_scale=cfg.curl_full_scale,
            invert_curl=cfg.invert_curl,
        )
        self.expr: dict[int, NoteExpression] = {}     # note -> its expression state

        self.out = _make_output(cfg, dry_run)
        self.out.configure_zone()

        self.group = cfg.ump_group
        self.ump_log = None
        if cfg.write_ump_log:
            self.ump_log = ump.UmpLogger(cfg.resolved_ump_log_path(), cfg.ump_group)
            self.ump_log.open()

        # notes arrive on the rtmidi thread; step() drains this
        self._events: collections.deque = collections.deque(maxlen=256)
        self._midi_in = None

        # last frame's fingertips, kept so a note-on can grab the finger that
        # played it even though the MIDI event and the video frame aren't synced
        self._tips_kb: list[tuple[int, float, float, str]] = []
        self._curl_by_tid: dict[int, float] = {}

    # ---- MIDI input ----------------------------------------------------
    def open_midi_in(self) -> bool:
        import rtmidi
        self._midi_in = rtmidi.MidiIn()
        ports = self._midi_in.get_ports()
        want = self.cfg.midi_in_match.lower()
        idx = next((i for i, n in enumerate(ports) if want and want in n.lower()),
                   0 if ports else None)
        if idx is None:
            print("No MIDI input ports. Plug the keyboard in, or use --selftest.")
            return False
        self._midi_in.open_port(idx)
        self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        self._midi_in.set_callback(lambda msg, _t: self._events.append(msg[0]))
        print(f"MIDI in : {ports[idx]}")
        print(f"MIDI out: {getattr(self.out, 'open_name', None) or '(no port)'}")
        return True

    def _drain_midi(self):
        while self._events:
            status, d1, d2 = (self._events.popleft() + [0, 0, 0])[:3]
            kind = status & 0xF0
            if kind == 0x90 and d2 > 0:
                self._note_on(d1, d2)
            elif kind == 0x80 or (kind == 0x90 and d2 == 0):
                self._note_off(d1)
            elif kind in (0xB0, 0xD0, 0xE0):
                self.out.passthrough(kind, d1, d2)      # pedal / wheel / etc

    def _note_on(self, note: int, vel: int):
        ch = self.out.note_on(note, vel)
        b = self.binder.note_on(note, ch, self._tips_kb, self._curl_by_tid)
        self.expr[note] = NoteExpression(self.expr_cfg)
        if self.ump_log:
            self.ump_log.log(
                ump.note_on(self.group, ch, note, vel << 9),
                f"note on  n{note} v{vel} ch{ch + 1} finger={b.finger_label} anchored={b.anchored}")

    def _note_off(self, note: int):
        ch = self.out.channel_for(note)
        self.out.note_off(note)
        self.binder.note_off(note)
        self.expr.pop(note, None)
        if self.ump_log and ch is not None:
            self.ump_log.log(ump.note_off(self.group, ch, note), f"note off n{note} ch{ch + 1}")

    # ---- per frame ------------------------------------------------
    def _to_keyboard_space(self, tips):
        """tips (image coords) -> ([(tid, u, v, label)], {tid: (u, v, label)})."""
        if not tips:
            return [], {}
        pts = np.array([[t.x, t.y] for t in tips], dtype=np.float32)
        kb = self.calib.image_to_keyboard(pts)
        lst, by_tid = [], {}
        for t, (u, v) in zip(tips, kb):
            label = FINGER_NAMES.get(t.landmark, "?")
            lst.append((t.tid, float(u), float(v), label))
            by_tid[t.tid] = (float(u), float(v), label)
        return lst, by_tid

    def step(self, frame, dt: float):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ts_ms = int(time.monotonic() * 1000)
        tips = self.ftrack.update(self.tracker.process(rgb, ts_ms))

        tips_kb, tips_by_tid = self._to_keyboard_space(tips)
        self._tips_kb = tips_kb
        self._curl_by_tid = {t.tid: t.curl for t in tips}

        self._drain_midi()
        self.binder.update(tips_by_tid, self._curl_by_tid)

        for b in self.binder.active():
            e = self.expr.get(b.note)
            if e is None:
                continue
            glide, slide, curl = e.update(b.du, b.dv, b.dcurl, dt)
            self.out.set_expression(b.note, "glide", glide)
            self.out.set_expression(b.note, "slide", slide)
            self.out.set_expression(b.note, "curl", curl)
            self._log_axes(b, glide, slide, curl)

        return tips, tips_kb

    def _log_axes(self, b, glide, slide, curl):
        if not self.ump_log:
            return
        g, ch, n = self.group, b.channel, b.note
        self.ump_log.log(ump.per_note_pitch_bend(g, ch, n, ump.bipolar_to_u32(glide)),
                         f"per-note bend   n{n} {glide:+.3f}")
        self.ump_log.log(ump.per_note_controller(g, ch, n, _CC_SLIDE, ump.bipolar_to_u32(slide)),
                         f"per-note slide  n{n} {slide:+.3f}")
        self.ump_log.log(ump.per_note_controller(g, ch, n, _CC_CURL, ump.bipolar_to_u32(curl)),
                         f"per-note curl   n{n} {curl:+.3f}")

    def close(self):
        try:
            self.out.close()
        except Exception:
            pass
        if self._midi_in:
            self._midi_in.close_port()
        if self.ump_log:
            self.ump_log.close()
        self.tracker.close()
