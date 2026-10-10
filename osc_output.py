"""Zero-install output path: drive Surge XT's command-line engine directly over
OSC. No virtual MIDI cable, no DAW, no admin rights.

Surge XT CLI exposes real per-note "Note Expressions" over OSC, which map
one-to-one onto this project's per-note model:

    /mnote      <note> <vel> <noteID>     note on   (vel 0 = release)
    /mnote/rel  <note> <relvel> <noteID>  note off
    /ne/pitch   <noteID> <semitones -120..120>
    /ne/timbre  <noteID> <0..1>
    /ne/pressure<noteID> <0..1>

Same public interface as MpeOutput so the engine doesn't care which is used.
"""
from __future__ import annotations

import pathlib
import socket
import subprocess
import time

from pythonosc.udp_client import SimpleUDPClient


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


class SurgeOscOutput:
    def __init__(self, host: str = "127.0.0.1", port: int = 53280,
                 bend_semitones: float = 2.0, surge_cli: str | None = None,
                 auto_start: bool = True, dry_run: bool = False,
                 audio_interface: str = "", buffer_size: int = 0, sample_rate: int = 0,
                 patch_dir: str = "", start_patch: str = "", gesture_map: dict | None = None):
        self.bend = bend_semitones
        self.dry_run = dry_run
        self.gesture_map = gesture_map or {
            "glide": {"target": "pitchbend"},
            "slide": {"target": "cc", "cc": 74},
            "curl": {"target": "cc", "cc": 1},
        }
        self._client = None if dry_run else SimpleUDPClient(host, port)
        self._note_to_id: dict[int, int] = {}
        self._next_id = 1
        self._proc = None
        self.opened = not dry_run
        self.open_name = f"Surge XT CLI  OSC {host}:{port}"

        if auto_start and not dry_run and surge_cli and pathlib.Path(surge_cli).exists():
            if _port_in_use(port):
                print(f"  OSC port {port} already bound - assuming Surge XT is running")
            else:
                cmd = [surge_cli, f"--osc-in-port={port}", "--no-stdin"]
                if audio_interface:
                    cmd.append(f"--audio-interface={audio_interface}")
                if buffer_size:
                    cmd.append(f"--buffer-size={buffer_size}")
                if sample_rate:
                    cmd.append(f"--sample-rate={sample_rate}")
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3.5)   # let it grab the audio device + bind the OSC port
                print(f"  started Surge XT CLI (pid {self._proc.pid}) on OSC port {port} "
                      f"(audio {audio_interface or 'default'})")

        # patch library
        self.patches: list[pathlib.Path] = []
        self.patch_idx = 0
        if patch_dir:
            pd = pathlib.Path(patch_dir)
            self.patches = sorted(pd.glob("*.fxp"))
            if self.patches and not dry_run:
                names = [p.stem for p in self.patches]
                if start_patch in names:
                    self.patch_idx = names.index(start_patch)
                self.load_patch(self.patch_idx)

    def load_patch(self, idx: int):
        if not self.patches:
            return
        self.patch_idx = idx % len(self.patches)
        p = self.patches[self.patch_idx].resolve()
        self._send("/patch/load", [str(p.with_suffix(""))])   # spec: absolute, no extension
        print(f"  patch: {p.stem}", flush=True)

    def next_patch(self):
        self.load_patch(self.patch_idx + 1)

    def prev_patch(self):
        self.load_patch(self.patch_idx - 1)

    def current_patch_name(self):
        return self.patches[self.patch_idx].stem if self.patches else "init"

    def show_editor(self):
        pass

    # ---- interface parity with MpeOutput ------------------------------
    def _send(self, addr, args):
        if self._client:
            self._client.send_message(addr, args)

    def configure_zone(self):
        pass

    # Surge's OSC parser expects all-float argument lists (typetag ",fff" etc);
    # a stray int in the noteID slot makes it drop the message. Everything is float.
    def note_on(self, note: int, velocity: int) -> int:
        nid = self._next_id
        self._next_id += 1
        self._note_to_id[note] = nid
        self._send("/mnote", [float(note), float(max(1, velocity)), float(nid)])
        self._send("/ne/pitch", [float(nid), 0.0])
        self._send("/ne/timbre", [float(nid), 0.5])
        return nid

    def note_off(self, note: int):
        nid = self._note_to_id.pop(note, None)
        if nid is not None:
            self._send("/mnote/rel", [float(note), 64.0, float(nid)])

    def channel_for(self, note: int):
        return self._note_to_id.get(note)

    def set_expression(self, note: int, axis: str, bipolar: float):
        spec = self.gesture_map.get(axis)
        nid = self._note_to_id.get(note)
        if not spec or nid is None:
            return
        v = max(-1.0, min(1.0, bipolar))
        target = spec.get("target", "none")
        if target == "pitchbend":
            self._send("/ne/pitch", [float(nid), v * self.bend])
        elif target == "cc":
            cc = int(spec.get("cc", 74))
            if cc == 74:
                # Surge has a real note-expression slot for timbre; use it
                self._send("/ne/timbre", [float(nid), 0.5 + v * 0.5])
            else:
                # any other CC just goes out as a plain channel CC
                self._send("/cc", [0, cc, round(64 + v * 63)])

    def passthrough(self, status: int, d1: int, d2: int):
        hi = status & 0xF0
        if hi == 0xB0:
            self._send("/cc", [0, int(d1), int(d2)])
        elif hi == 0xD0:
            self._send("/chan_at", [0, int(d1)])
        elif hi == 0xE0:
            bend = ((d2 << 7 | d1) - 8192) / 8192.0
            self._send("/pbend", [0, float(bend)])

    def all_notes_off(self):
        for note, nid in list(self._note_to_id.items()):
            self._send("/mnote/rel", [float(note), 64.0, nid])
        self._note_to_id.clear()

    def close(self):
        self.all_notes_off()
        if self._proc is not None:
            self._proc.terminate()
