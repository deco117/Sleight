"""
Live MIDI 2.0 UMP output - genuine Universal MIDI Packets on a real Windows
MIDI Services endpoint, not MPE.

Why this exists: mpe_output.py sends MPE because MIDI 2.0 UMP has no
Python-importable transport - python-rtmidi is MIDI-1.0-byte-stream-only, and
there is no PyPI package for Windows.Devices.Midi2 (winsdk only projects the
base Windows SDK, which doesn't include it; the microsoft/MIDI GitHub repo
ships no prebuilt Python bindings either - checked directly). What Windows
MIDI Services *does* ship is a C++/WinRT and C#/WinRT component
(Microsoft.Windows.Devices.Midi2, GitHub-only nupkg - see
https://github.com/microsoft/MIDI/releases). So this backend drives that API
from a tiny companion .NET console app, midi2_bridge/ (source: Program.cs,
built with `dotnet publish`, published exe at
midi2_bridge/publish/midi2_bridge.exe), over a two-line stdin/stdout
protocol. All UMP *message construction* still happens here in Python, via
the exact same ump.py word-builders the logger uses - this module only owns
opening the live connection and piping the already-built 32-bit words out.

Single fixed channel, not MPE's one-channel-per-note: in MIDI 2.0 UMP,
per-note pitch bend / per-note controller / poly pressure messages already
address a specific sounding voice via (group, channel, note) together - the
note number is part of the address, not just a MIDI 1.0-style "which key".
Since this keyboard never has two different notes both meaning the same
key at the same time, one constant channel is sufficient and correct; MPE's
channel-per-note allocator (mpe_output.py's _alloc/_busy machinery) exists
only to work around MIDI 1.0's lack of that addressing, which doesn't apply
here. See MIDI 2.0 UMP 1.1 sec. on Channel Voice Message addressing.

IMPORTANT (process-startup safety): nothing in this module touches the
Windows MIDI Services SDK at import time. The subprocess is only spawned
inside Midi2UmpOutput.__init__, which only runs when output_mode ==
"midi2_ump" is actually selected in config.json. Importing this module (as
engine.py does unconditionally, the same way it already imports MpeOutput/
VstHostOutput/SurgeOscOutput) is always safe on a machine that has never
heard of Windows MIDI Services - the existing "mpe" mode is completely
unaffected. If the bridge exe is missing, or the SDK runtime isn't installed
on that machine, __init__ prints a clear diagnostic and leaves the backend
in a disabled (self.opened = False) no-op state, exactly like MpeOutput does
when it can't find a matching MIDI port.
"""
from __future__ import annotations

import pathlib
import queue
import subprocess
import threading

import ump

DEFAULT_GESTURE_MAP = {
    "glide": {"target": "pitchbend"},
    "slide": {"target": "cc", "cc": 74},
    "curl":  {"target": "cc", "cc": 1},
}

# Fixed channel every note is sent on - see module docstring.
_CHANNEL = 0

_HANDSHAKE_TIMEOUT_S = 5.0
_SEND_ACK_TIMEOUT_S = 1.0

_SDK_INSTALL_HINT = (
    "    Windows MIDI Services isn't available (or the bridge couldn't reach it).\n"
    "    Install either the App SDK:  winget install Microsoft.MIDI.SDK\n"
    "    or the in-box preview (Windows 11 25H2+): github.com/microsoft/MIDI/releases\n"
    "    then restart Sleight. Falling back to no MIDI 2.0 output this run -\n"
    "    switch output_mode back to \"mpe\" in config.json if you need sound now."
)


def _default_bridge_exe() -> pathlib.Path:
    # Same "app dir" resolution as config.py's HERE - NOT pathlib.Path(__file__),
    # which doesn't reliably point at the distribution folder once PyInstaller
    # has frozen this module into its bundle. Reusing config.HERE (rather than
    # reimplementing the sys.frozen check here) means there's exactly one place
    # that logic lives.
    from config import HERE
    return HERE / "midi2_bridge" / "publish" / "midi2_bridge.exe"


def _default_bridge_exes() -> list[pathlib.Path]:
    from config import HERE
    return [
        HERE / "midi2_bridge" / "publish" / "midi2_bridge.exe",
        HERE / "midi2_bridge_inbox" / "publish" / "midi2_bridge_inbox.exe",
    ]


class Midi2UmpOutput:
    """Same shape as MpeOutput (note_on/off, channel_for, set_expression,
    passthrough, all_notes_off, configure_zone, patch/editor no-ops, close) so
    engine.py can use either interchangeably based on output_mode."""

    def __init__(self, port_match: str, group: int = 0,
                 dry_run: bool = False, gesture_map: dict | None = None,
                 bridge_exe: str | pathlib.Path | None = None):
        self.group = group
        self.dry_run = dry_run
        self.gesture_map = gesture_map or DEFAULT_GESTURE_MAP
        self.channel = _CHANNEL

        self._active_notes: set[int] = set()
        self._proc: subprocess.Popen | None = None
        self._out_q: "queue.Queue[str]" = queue.Queue()
        self._reader: threading.Thread | None = None

        self.opened = False
        self.open_name = None

        if dry_run:
            return

        # Two bridges ship: midi2_bridge (built against the separately-installed App
        # SDK runtime) and midi2_bridge_inbox (built against the in-box API that
        # Windows 11 25H2+ is adopting, preview 9 onward). Whichever one the machine
        # actually supports starts cleanly; the other prints STARTFAIL straight away.
        # An explicit bridge_exe override means "use exactly this one".
        candidates = [pathlib.Path(bridge_exe)] if bridge_exe else _default_bridge_exes()
        existing = [c for c in candidates if c.exists()]
        if not existing:
            print(f"  ! midi2_ump: bridge executable not found at {candidates[0]}\n"
                  f"    Build it with: cd midi2_bridge && dotnet publish -c Release "
                  f"-r win-x64 --self-contained false -o publish")
            return

        failures: list[str] = []
        for exe in existing:
            reply = self._start_bridge(exe, port_match)
            if reply is None:
                continue  # couldn't even launch/handshake - already reported
            if reply.startswith("PONG"):
                self.opened = True
                self.open_name = reply[len("PONG "):].strip() or "(Windows MIDI Services endpoint)"
                return
            failures.append(f"{exe.parent.parent.name}: {reply}")
            self._shutdown_proc()

        for f in failures:
            print(f"  ! midi2_ump: {f}")
        print(_SDK_INSTALL_HINT)

    def _start_bridge(self, exe: pathlib.Path, port_match: str) -> str | None:
        """Launch one bridge and return its first reply line ("PONG ..." or
        "STARTFAIL ..."), or None if it couldn't be launched at all."""
        self._out_q = queue.Queue()
        try:
            self._proc = subprocess.Popen(
                [str(exe), "--port", port_match or ""],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as e:
            print(f"  ! midi2_ump: couldn't launch bridge process: {e}")
            return None

        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()

        # Handshake: the bridge prints exactly one line before it's ready for
        # commands - either "PONG <name>" after a PING, or "STARTFAIL <reason>".
        self._send_raw("PING")
        try:
            return self._out_q.get(timeout=_HANDSHAKE_TIMEOUT_S)
        except queue.Empty:
            print(f"  ! midi2_ump: {exe.parent.parent.name} didn't respond")
            self._shutdown_proc()
            return None

    # ---- bridge process plumbing --------------------------------------
    def _pump_stdout(self):
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            self._out_q.put(line.rstrip("\n"))

    def _send_raw(self, line: str):
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.opened = False

    def _send_words(self, words: tuple[int, int]):
        if not self.opened:
            return
        self._send_raw(f"SEND {words[0]:08X} {words[1]:08X}")
        try:
            reply = self._out_q.get(timeout=_SEND_ACK_TIMEOUT_S)
            if reply != "OK":
                print(f"  ! midi2_ump: send failed: {reply}")
        except queue.Empty:
            # Don't let a slow/dead bridge stall the 60Hz expression loop -
            # note it and keep going; the next handshake-style check happens
            # naturally on the next send.
            pass

    def _shutdown_proc(self):
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.write("QUIT\n")
                self._proc.stdin.flush()
            self._proc.wait(timeout=2.0)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    # ---- notes ------------------------------------------------------
    def note_on(self, note: int, velocity: int) -> int:
        self._active_notes.add(note)
        velocity16 = min(0xFFFF, max(0, velocity) << 9)   # 7-bit -> 16-bit
        self._send_words(ump.note_on(self.group, self.channel, note, velocity16))
        return self.channel

    def note_off(self, note: int):
        self._active_notes.discard(note)
        self._send_words(ump.note_off(self.group, self.channel, note))

    def channel_for(self, note: int):
        return self.channel if note in self._active_notes else None

    # ---- expression ----------------------------------------------
    def set_expression(self, note: int, axis: str, bipolar: float):
        spec = self.gesture_map.get(axis)
        if not spec or note not in self._active_notes:
            return
        v = max(-1.0, min(1.0, bipolar))
        target = spec.get("target", "none")
        if target == "pitchbend":
            words = ump.per_note_pitch_bend(self.group, self.channel, note,
                                             ump.bipolar_to_u32(v))
        elif target == "cc":
            index = int(spec.get("cc", 74))
            words = ump.per_note_controller(self.group, self.channel, note, index,
                                             ump.bipolar_to_u32(v))
        else:
            return
        self._send_words(words)

    def passthrough(self, status: int, d1: int, d2: int):
        # Sustain pedal / mod wheel / the keyboard's own aftertouch, as raw
        # MIDI 1.0 bytes from the input side. There's no MIDI 1.0 Channel
        # Voice UMP builder in ump.py (it only builds MIDI 2.0 CV, message
        # type 0x4) and nothing in the current gesture set routes through
        # here, so this is deliberately a no-op rather than a half-translated
        # guess. Revisit if/when a passthrough control actually needs to
        # reach a UMP endpoint.
        pass

    def all_notes_off(self):
        for note in list(self._active_notes):
            self.note_off(note)

    # patch / editor controls only mean something for the in-process synths
    def configure_zone(self): pass
    def next_patch(self): pass
    def prev_patch(self): pass
    def current_patch_name(self): return ""
    def show_editor(self): pass

    def close(self):
        if not self.opened:
            return
        try:
            self.all_notes_off()
        finally:
            self._shutdown_proc()
            self.opened = False
