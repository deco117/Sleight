"""
All the knobs, in one place. Loads config.json from next to this file (or next
to the .exe when frozen) and falls back to the dataclass defaults for anything
it doesn't find. Unknown keys in the JSON are ignored, so an old config file
won't break a newer build.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
from dataclasses import dataclass, field

# Frozen by PyInstaller -> the "app dir" is where the .exe sits, so config.json
# and calibration.json land next to it. Running from source -> next to this file.
if getattr(sys, "frozen", False):
    HERE = pathlib.Path(sys.executable).resolve().parent
else:
    HERE = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
CALIBRATION_PATH = HERE / "calibration.json"


@dataclass
class Config:
    # ---- where the notes go -----------------------------------------------
    #   "mpe"       MPE out a virtual MIDI port (loopMIDI). Shows up as a MIDI
    #               input in any DAW. The default, and the one that's tested.
    #   "midi2_ump" genuine MIDI 2.0 UMP (32-bit per-note pitch bend/CCs, not
    #               MPE's channel-per-note workaround) over a real Windows
    #               MIDI Services endpoint. Needs Windows MIDI Services' App
    #               SDK installed (winget install Microsoft.MIDI.SDK) and the
    #               midi2_bridge companion exe built - see midi2_output.py.
    #               midi_out_match below picks the endpoint, same as "mpe".
    #   "vst_host"  load a VST3 instrument in-process and play it here.
    #   "surge_osc" drive a Surge XT CLI over OSC. Needs a SurgeXT/ folder;
    #               not shipped in the build.
    output_mode: str = "mpe"

    # ---- MIDI in / out --------------------------------------------------
    # Case-insensitive substring. First port whose name contains it wins.
    #   python main.py --list-ports   to see the names.
    midi_in_match: str = ""            # your keyboard  ("" = first input port)
    midi_out_match: str = "Sleight"    # the loopMIDI port (or, in midi2_ump
                                        # mode, the Windows MIDI Services
                                        # endpoint) your DAW listens on
    midi2_bridge_exe: str = ""         # midi2_ump only. "" = the default
                                        # build output, midi2_bridge/publish/
                                        # midi2_bridge.exe next to this file.

    # ---- keyboard size ------------------------------------------------
    # MIDI note number of the lowest and highest physical keys.
    #   25-key = 48..72   49-key = 36..84   61-key = 36..96   88-key = 21..108
    #   python main.py --midi-monitor   to find yours.
    lowest_note: int = 36
    highest_note: int = 96

    # ---- MPE zone ----------------------------------------------------
    mpe_master_channel: int = 1          # 1-based, lower zone
    mpe_member_channels: int = 15        # one per simultaneously-expressive note
    per_note_pitch_bend_range: int = 2   # semitones. Set your synth's MPE bend to match.
                                          # A wide range (e.g. 48) sounds fine on paper but
                                          # turns a small, musical finger-glide into a huge,
                                          # siren-like warble in practice - 2 (a whole tone)
                                          # is the usual MPE convention for a reason.

    # ---- camera ----------------------------------------------------
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    flip_horizontal: bool = True         # mirror the view so it reads like a monitor

    # ---- what you see while running --------------------------
    # "full" (cinematic visualiser), "plain" (flat debug HUD), or "none"
    # (no drawing at all - fastest, for a weak CPU). --view on the command
    # line overrides this for one run without changing the saved default.
    default_view: str = "full"
    draw_hand_skeleton: bool = True      # the luminous hand overlay - off saves draw time on a weak CPU

    # ---- hand tracking ------------------------------------------
    max_hands: int = 2
    min_detection_confidence: float = 0.6
    min_tracking_confidence: float = 0.5

    # ---- expression feel -------------------------------------
    # "full_scale" = how far the finger has to drift for a full-scale value.
    # Distances are in keyboard-widths (glide) or key-depths (slide). Smaller
    # number = more sensitive.
    glide_full_scale: float = 0.06       # sideways slide
    slide_full_scale: float = 0.5        # forward/back slide
    curl_full_scale: float = 0.35        # finger curl
    glide_deadzone: float = 0.004        # sideways drift below this is treated as jitter
    smoothing_ms: float = 45.0           # low-pass on all three streams
    send_rate_hz: float = 60.0           # how often expression is pushed to MIDI

    invert_glide: bool = False
    invert_slide: bool = False
    invert_curl: bool = False

    # ---- what each movement sends ---------------------------
    # One entry per axis. target is "pitchbend" (per-note bend), "cc" (needs a
    # "cc" number 0-127), or "none". Whatever CC you pick, MIDI-learn it to a
    # parameter at the synth end. In MPE mode the CC arrives on the note's own
    # member channel, so per-note learn works too.
    #   glide = sideways slide   slide = forward/back slide   curl = finger curl
    gesture_map: dict = field(default_factory=lambda: {
        "glide": {"target": "pitchbend"},
        "slide": {"target": "cc", "cc": 74},
        "curl":  {"target": "cc", "cc": 1},
    })

    # ---- MIDI 2.0 log ------------------------------------
    # The engine builds real MIDI 2.0 UMP words for everything it does,
    # regardless of output_mode. With output_mode = "midi2_ump" those words
    # also go out live over a real Windows MIDI Services endpoint (see
    # midi2_output.py); most people are still on "mpe" though (no extra
    # install needed), so this log is what lets you inspect the MIDI 2.0 side
    # - the full 32-bit per-note resolution MPE can't carry - independent of
    # which output_mode is active.
    write_ump_log: bool = True
    ump_log_path: str = "session.midi2.log"
    ump_group: int = 0

    # ---- host a VST3 here (output_mode = "vst_host") --------------
    vst_plugin_path: str = ""            # path to a .vst3 ("" = look for a bundled Surge)
    vst_preset_dir: str = ""             # folder of .vstpreset files, 'p' cycles them
    vst_start_preset: str = ""
    vst_block_size: int = 512
    vst_sample_rate: int = 48000
    audio_output_device: str = ""        # name substring, "" = system default

    # ---- Surge XT over OSC (output_mode = "surge_osc") -----------
    surge_osc_host: str = "127.0.0.1"
    surge_osc_port: int = 53280
    surge_bend_semitones: float = 2.0    # full glide -> this many semitones
    surge_cli_path: str = "SurgeXT/surge-xt-cli.exe"
    surge_auto_start: bool = True
    surge_audio_interface: str = ""      # e.g. "3.1"; "" = Surge's default. -l to list.
    surge_buffer_size: int = 256
    surge_sample_rate: int = 48000
    surge_patch_dir: str = "SurgeXT/patches"
    surge_start_patch: str = "Juno-60 Strings"

    def resolved_surge_cli(self) -> str:
        p = pathlib.Path(self.surge_cli_path)
        return str(p if p.is_absolute() else HERE / p)

    def resolved_ump_log_path(self) -> pathlib.Path:
        p = pathlib.Path(self.ump_log_path)
        return p if p.is_absolute() else HERE / p

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(dataclasses.asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            for k, v in json.loads(CONFIG_PATH.read_text()).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg
