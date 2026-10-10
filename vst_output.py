"""Host any VST3 instrument in-process and play it live.

This is the synth-agnostic output path: point Sleight at your own Serum /
Pigments / Kontakt / whatever, and the webcam per-note expression drives it.
No DAW, no virtual MIDI cable, no separate process.

pedalboard loads the plugin; a sounddevice output stream renders it in its
audio callback. Per-note expression is sent as MPE (one member channel per
sounding note) which every modern MPE synth understands.
"""
from __future__ import annotations

import collections
import pathlib
import threading

import numpy as np

try:
    import pedalboard as pb
    import sounddevice as sd
except Exception as e:  # pragma: no cover
    pb = None
    sd = None
    _IMPORT_ERR = e


# bundled fallback synth
_BUNDLED_SURGE = "SurgeXT/Surge XT.vst3/Contents/x86_64-win/Surge XT.vst3"


def resolve_vst3(path: str) -> str:
    """Accept either a .vst3 bundle folder or the inner binary; return a
    path pedalboard can load."""
    p = pathlib.Path(path)
    if p.is_dir():
        inner = p / "Contents" / "x86_64-win" / p.name
        if inner.exists():
            return str(inner)
    return str(p)


class VstHostOutput:
    def __init__(self, plugin_path: str = "", preset_dir: str = "", start_preset: str = "",
                 bend_semitones: float = 48.0, sample_rate: int = 48000, block_size: int = 512,
                 audio_device: str = "", app_dir: pathlib.Path | None = None, dry_run: bool = False,
                 gesture_map: dict | None = None):
        self.bend = bend_semitones
        self.sr = sample_rate
        self.blk = block_size
        self.dry_run = dry_run
        self.open_name = None
        self.gesture_map = gesture_map or {
            "glide": {"target": "pitchbend"},
            "slide": {"target": "cc", "cc": 74},
            "curl": {"target": "cc", "cc": 1},
        }

        # MPE lower zone: master ch 0, members ch 1..15
        self.master = 0
        self.members = list(range(1, 16))
        self._note_to_ch: dict[int, int] = {}
        self._ch_busy = {c: False for c in self.members}
        self._rr = 0

        self._q: collections.deque = collections.deque()
        self._plugin = None
        self._stream = None
        self._lock = threading.Lock()

        # preset library (.vstpreset only - VST3 preset format)
        base = app_dir or pathlib.Path.cwd()
        self.presets: list[pathlib.Path] = []
        self.preset_idx = 0
        if preset_dir:
            pd = (base / preset_dir) if not pathlib.Path(preset_dir).is_absolute() else pathlib.Path(preset_dir)
            self.presets = sorted(pd.glob("*.vstpreset"))

        if dry_run:
            return
        if pb is None:
            raise SystemExit(f"pedalboard/sounddevice import failed: {_IMPORT_ERR}")

        # resolve output device + its native sample rate (avoid resampling)
        dev = None
        if audio_device:
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and audio_device.lower() in d["name"].lower():
                    dev = i
                    break
        dev_info = sd.query_devices(dev if dev is not None else sd.default.device[1])
        native_sr = int(round(dev_info["default_samplerate"]))
        if not sample_rate or abs(native_sr - sample_rate) > 1:
            self.sr = native_sr

        path = plugin_path or str((base or pathlib.Path.cwd()) / _BUNDLED_SURGE)
        path = resolve_vst3(path)
        print(f"  loading synth: {pathlib.Path(path).stem} ...", flush=True)
        self._plugin = pb.load_plugin(path)
        if not self._plugin.is_instrument:
            raise SystemExit(f"{path} is not an instrument plugin")
        self.open_name = self._plugin.name

        self._plugin.process([], duration=self.blk / self.sr, sample_rate=self.sr,
                             buffer_size=self.blk, reset=True, num_channels=2)
        self._stream = sd.OutputStream(samplerate=self.sr, blocksize=self.blk, channels=2,
                                       dtype="float32", device=dev, callback=self._audio_cb)
        self._stream.start()
        print(f"  audio: {sd.query_devices(self._stream.device)['name']}  "
              f"{self.sr} Hz / {self.blk} samples", flush=True)

        if start_preset:
            names = [p.stem for p in self.presets]
            if start_preset in names:
                self.load_preset(names.index(start_preset))

    # ---- audio callback -------------------------------------------
    def _audio_cb(self, outdata, frames, time_info, status):
        msgs = []
        while self._q:
            try:
                msgs.append(self._q.popleft())
            except IndexError:
                break
        try:
            with self._lock:
                audio = self._plugin.process(msgs, duration=frames / self.sr, sample_rate=self.sr,
                                             buffer_size=frames, reset=False, num_channels=2)
        except Exception:
            outdata.fill(0)
            return
        a = np.ascontiguousarray(audio.T)          # (channels, N) -> (N, channels)
        if a.shape[0] < frames:
            outdata[:a.shape[0]] = a
            outdata[a.shape[0]:] = 0
        else:
            outdata[:] = a[:frames]

    # ---- MIDI helpers --------------------------------------------
    def _push(self, *b):
        self._q.append((bytes(b), 0.0))

    def _cc(self, ch, n, v):
        self._push(0xB0 | ch, n & 0x7F, v & 0x7F)

    def _rpn(self, ch, msb, lsb, val):
        self._cc(ch, 101, msb); self._cc(ch, 100, lsb); self._cc(ch, 6, val)
        self._cc(ch, 101, 127); self._cc(ch, 100, 127)

    def _pitchbend(self, ch, v14):
        v14 = max(0, min(16383, int(v14)))
        self._push(0xE0 | ch, v14 & 0x7F, (v14 >> 7) & 0x7F)

    # ---- interface parity ---------------------------------------
    def configure_zone(self):
        if self.dry_run:
            return
        self._rpn(self.master, 0x00, 0x06, len(self.members))       # MPE config
        for ch in [self.master, *self.members]:
            self._rpn(ch, 0x00, 0x00, int(self.bend))               # per-note bend range
            self._pitchbend(ch, 8192)
            self._cc(ch, 74, 64)

    def _alloc(self) -> int:
        for _ in range(len(self.members)):
            ch = self.members[self._rr % len(self.members)]
            self._rr += 1
            if not self._ch_busy[ch]:
                self._ch_busy[ch] = True
                return ch
        ch = self.members[self._rr % len(self.members)]
        self._rr += 1
        return ch

    def note_on(self, note: int, velocity: int) -> int:
        ch = self._alloc()
        self._note_to_ch[note] = ch
        self._pitchbend(ch, 8192)
        self._cc(ch, 74, 64)
        self._push(0xD0 | ch, 0)
        self._push(0x90 | ch, note & 0x7F, max(1, velocity) & 0x7F)
        return ch

    def note_off(self, note: int):
        ch = self._note_to_ch.pop(note, None)
        if ch is None:
            return
        self._push(0x80 | ch, note & 0x7F, 0)
        self._pitchbend(ch, 8192)
        self._ch_busy[ch] = False

    def channel_for(self, note: int):
        return self._note_to_ch.get(note)

    def set_expression(self, note: int, axis: str, bipolar: float):
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
        self._push((status & 0xF0) | self.master, d1, d2)

    def all_notes_off(self):
        for ch in [self.master, *self.members]:
            self._cc(ch, 123, 0)
            self._pitchbend(ch, 8192)

    # ---- presets / editor -------------------------------------
    def load_preset(self, idx: int):
        if not self.presets or self._plugin is None:
            return
        self.preset_idx = idx % len(self.presets)
        try:
            with self._lock:
                self._plugin.load_preset(str(self.presets[self.preset_idx]))
            print(f"  preset: {self.presets[self.preset_idx].stem}", flush=True)
        except Exception as e:
            print(f"  preset load failed: {e}", flush=True)

    def next_patch(self):
        if self.presets:
            self.load_preset(self.preset_idx + 1)

    def prev_patch(self):
        if self.presets:
            self.load_preset(self.preset_idx - 1)

    def current_patch_name(self):
        return self.presets[self.preset_idx].stem if self.presets else (self.open_name or "")

    def show_editor(self):
        if self._plugin is not None:
            threading.Thread(target=self._plugin.show_editor, daemon=True).start()

    def close(self):
        if self.dry_run:
            return
        try:
            self.all_notes_off()
        except Exception:
            pass
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
