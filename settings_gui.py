"""
Settings window - a friendlier front end for config.json than typing CLI
flags and hand-editing JSON. Ties together the things that were spread across
--pick-camera / --calibrate / --midi-monitor / --view / gesture_map: MIDI
ports, camera + calibration, what you see while running, and what each
finger axis does (on/off, pitch-bend-or-CC, which CC, inverted, how
sensitive). Everything here just reads and writes the same Config object the
CLI uses - this is not a second config system.

tkinter, not a new dependency - it ships with Python. The camera-pick and
calibrate buttons call straight into main.py's existing OpenCV-window flows;
they block this window while they run, the same way a modal dialog would,
then this window refreshes to show the result.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

from config import CALIBRATION_PATH, Config

AXES = [
    ("glide", "Glide", "sideways slide on the key"),
    ("slide", "Slide", "forward / back slide on the key"),
    ("curl", "Curl", "curl or flatten the finger"),
]
RESOLUTIONS = [(640, 480), (960, 540), (1280, 720)]
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _note_name(n: int) -> str:
    return f"{_NOTE_NAMES[n % 12]}{n // 12 - 1}"


def _open_channel_link():
    try:
        webbrowser.open("https://www.youtube.com/@deancoyle")
    except Exception:
        pass


def _set_icon(root: tk.Tk):
    """Give this Tk root Sleight's own icon instead of the default feather -
    main.py already does the equivalent for the OpenCV window (see
    _set_window_icon there), but that's a separate Win32 call against a
    non-Tk window and doesn't cover these Settings/gesture-panel/UMP-viewer
    windows. Every Toplevel created with this root as its master inherits
    the icon automatically (standard Tkinter/Windows behaviour, no need to
    set it again on each one) - so this only needs calling once, right
    after each hidden root is created. Best-effort: a missing icon.ico
    (e.g. running from source without ever having built) isn't worth
    failing over."""
    try:
        root.iconbitmap(default=str(CALIBRATION_PATH.parent / "icon.ico"))
    except Exception:
        pass


def _install_safe_callback_handler(root: tk.Tk):
    """Tkinter's default reaction to an exception inside a widget callback
    (a button, a trace, a Spinbox command) is to print a traceback to
    stderr and carry on - the process itself survives. But the frozen
    build runs with a console window most people never look at, so from
    the outside that looks exactly like nothing happened, or like the
    window's stuck - not reassuring at a demo. This adds a small on-screen
    message on top of the traceback, for anything that reaches this handler
    at all. (It won't catch everything - SystemExit deliberately bypasses
    this and every other Tkinter callback handler, which is why the actual
    camera-in-use crash was fixed at its source in camera.py instead of
    papered over here.)"""
    def _handler(exc, val, tb):
        import traceback
        traceback.print_exception(exc, val, tb)
        try:
            messagebox.showerror("Sleight", f"That action hit a problem and was cancelled:\n\n{val}")
        except Exception:
            pass
    root.report_callback_exception = _handler


class SettingsWindow(tk.Toplevel):
    """The full settings window: MIDI ports, camera/calibration, hand count,
    key range, and gestures - everything, all in one ttk.Notebook. A
    Toplevel, not its own tk.Tk() root - a process should only ever have one
    real Tk root alive at once. Both entry points below give it one:
    run_settings() spins up a throwaway hidden root for the standalone
    `--settings` launch, open_full_settings() reuses the run loop's shared
    hidden root so this can be popped open mid-session (the 's' key,
    caps or not - both keycodes route here, see main.py) without a second
    root fighting the first for the event loop.

    Two separate crashes have hit this window before, both fixed now:
    _build_midi_tab() used to call rtmidi.MidiIn().get_ports() with no
    error handling while every other rtmidi call in this file was
    defensively wrapped. And the real "menus crash" - the camera and
    calibrate buttons below opening a second handle on a camera the live
    session already has open, which raised SystemExit deep inside
    Tkinter's callback machinery. Tkinter deliberately re-raises
    SystemExit instead of routing it through the normal error handling
    (see _install_safe_callback_handler above) - so a plain try/except
    here wouldn't have been enough on its own; camera.py no longer raises
    SystemExit for this at all, it's an ordinary, catchable exception now.
    GesturePanel below is a separate, lighter live-apply panel that exists
    in case a no-restart quick-tweak surface is wanted later; nothing
    currently opens it."""

    def __init__(self, master, cfg: Config):
        super().__init__(master)
        self.cfg = cfg
        self.result = False   # True only if "Save && Run" was clicked
        self.title("Sleight - Settings")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        # NOT self.transient(master) + self.grab_set() here: grab_set() on a
        # freshly-constructed Toplevel that isn't mapped/viewable yet throws
        # "TclError: grab failed: window not viewable" - and master here is
        # often the deliberately-withdrawn hidden root, which makes it worse.
        # This was the actual cause of "full settings is not opening" - the
        # window was raising during construction, before a single widget got
        # built. Not modal is a fine trade for actually opening.

        pad = {"padx": 10, "pady": 6}
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        midi_tab = ttk.Frame(nb)
        cam_tab = ttk.Frame(nb)
        gesture_tab = ttk.Frame(nb)
        nb.add(midi_tab, text="MIDI")
        nb.add(cam_tab, text="Camera && Calibration")
        nb.add(gesture_tab, text="Gestures")

        self._build_midi_tab(midi_tab, pad)
        self._build_camera_tab(cam_tab, pad)
        self._build_gesture_tab(gesture_tab, pad)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="Save", command=self._save).pack(side="right", padx=6)
        ttk.Button(btns, text="Save && Run", command=self._save_and_run).pack(side="right")

        link = tk.Label(btns, text="More from Dean Coyle Audio (YouTube)",
                        fg="#5fa8e0", cursor="hand2", font=("", 9, "underline"))
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: _open_channel_link())

    # ---- MIDI tab --------------------------------------------------
    def _build_midi_tab(self, f, pad):
        # Every other rtmidi call in this file is wrapped (see
        # _open_range_midi) because a missing backend / busy port / no
        # devices at all can raise here - this one wasn't, and an
        # uncaught exception while building the FIRST tab took the whole
        # settings window (and the exception propagates straight up through
        # _handle_key with nothing to catch it) down with it: the "s
        # crashes the program" report. Empty lists just mean the dropdowns
        # show no ports instead of the window never opening.
        try:
            import rtmidi
            in_ports = rtmidi.MidiIn().get_ports()
            out_ports = rtmidi.MidiOut().get_ports()
        except Exception:
            in_ports, out_ports = [], []

        # label <-> config value. Order matters: this is the dropdown order too.
        output_mode_labels = [
            ("MPE (any MIDI 1.0 synth/DAW)", "mpe"),
            ("MIDI 2.0 (Windows MIDI Services)", "midi2_ump"),
        ]
        self._output_mode_by_label = dict(output_mode_labels)
        label_by_mode = {v: k for k, v in output_mode_labels}

        ttk.Label(f, text="Output mode").grid(row=0, column=0, sticky="w", **pad)
        self.output_mode = tk.StringVar(
            value=label_by_mode.get(self.cfg.output_mode, output_mode_labels[0][0]))
        ttk.Combobox(f, textvariable=self.output_mode,
                    values=[label for label, _ in output_mode_labels],
                    width=38, state="readonly").grid(row=0, column=1, **pad)
        ttk.Label(f, text="Needs \"Save && Run\" (not just Save) to take effect - it restarts "
                          "the session with the new output.",
                  foreground="#666").grid(row=1, column=0, columnspan=2, sticky="w", padx=10)

        ttk.Label(f, text="Keyboard input").grid(row=2, column=0, sticky="w", **pad)
        self.midi_in = tk.StringVar(value=self.cfg.midi_in_match or "(auto - first input)")
        in_values = ["(auto - first input)"] + in_ports
        ttk.Combobox(f, textvariable=self.midi_in, values=in_values,
                    width=38, state="readonly").grid(row=2, column=1, **pad)

        ttk.Label(f, text="Output port name").grid(row=3, column=0, sticky="w", **pad)
        self.midi_out = tk.StringVar(value=self.cfg.midi_out_match)
        ttk.Combobox(f, textvariable=self.midi_out, values=out_ports or [self.cfg.midi_out_match],
                    width=38).grid(row=3, column=1, **pad)
        ttk.Label(f, text="The loopMIDI port name (MPE) or Windows MIDI Services endpoint "
                          "name (MIDI 2.0) your DAW/synth listens on. " +
                          (("seen now: " + ", ".join(out_ports)) if out_ports else
                           "no loopMIDI output ports seen right now - that's normal for MIDI 2.0 mode."),
                  foreground="#666", wraplength=420, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", padx=10)

        ttk.Label(f, text="Pitch bend range (semitones)").grid(row=5, column=0, sticky="w", **pad)
        self.bend_range = tk.IntVar(value=self.cfg.per_note_pitch_bend_range)
        ttk.Spinbox(f, from_=1, to=96, textvariable=self.bend_range, width=6).grid(
            row=5, column=1, sticky="w", **pad)
        ttk.Label(f, text="Match this in your synth's MPE settings (MPE mode only).",
                  foreground="#666").grid(row=6, column=0, columnspan=2, sticky="w", padx=10)

    # ---- Camera & Calibration tab -----------------------------------
    def _build_camera_tab(self, f, pad):
        ttk.Label(f, text="Capture resolution").grid(row=0, column=0, sticky="w", **pad)
        cur = (self.cfg.camera_width, self.cfg.camera_height)
        labels = [f"{w}x{h}" for w, h in RESOLUTIONS]
        if cur not in RESOLUTIONS:
            labels.append(f"{cur[0]}x{cur[1]} (current)")
        self.resolution = tk.StringVar(value=f"{cur[0]}x{cur[1]}" if cur in RESOLUTIONS
                                       else f"{cur[0]}x{cur[1]} (current)")
        ttk.Combobox(f, textvariable=self.resolution, values=labels, width=20,
                    state="readonly").grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(f, text="Camera index").grid(row=1, column=0, sticky="w", **pad)
        self.camera_label = ttk.Label(f, text=str(self.cfg.camera_index))
        self.camera_label.grid(row=1, column=1, sticky="w", **pad)
        ttk.Button(f, text="Preview && pick camera...", command=self._pick_camera).grid(
            row=1, column=2, **pad)

        ttk.Label(f, text="Key range").grid(row=2, column=0, sticky="w", **pad)
        self.range_label = ttk.Label(f, text=self._range_text())
        self.range_label.grid(row=2, column=1, sticky="w", **pad)
        ttk.Button(f, text="Detect from keyboard...", command=self._detect_range).grid(
            row=2, column=2, **pad)

        # Manual override, for when you can't play the extreme keys to hand
        # (a broken key, a controller you're not next to) or just want to
        # type the range in - the detect button above still saves straight
        # into these same fields.
        manual = ttk.Frame(f)
        manual.grid(row=3, column=0, columnspan=3, sticky="w", padx=10)
        ttk.Label(manual, text="  or set directly:", foreground="#666").pack(side="left")
        ttk.Label(manual, text="lowest").pack(side="left", padx=(10, 2))
        self.lowest_note = tk.IntVar(value=self.cfg.lowest_note)
        self._lowest_spinbox = ttk.Spinbox(manual, from_=0, to=127, textvariable=self.lowest_note,
                                           width=5, command=self._on_manual_range)
        self._lowest_spinbox.pack(side="left")
        self.lowest_name = ttk.Label(manual, text=_note_name(self.cfg.lowest_note),
                                     foreground="#666", width=4)
        self.lowest_name.pack(side="left", padx=(4, 10))
        ttk.Label(manual, text="highest").pack(side="left", padx=(0, 2))
        self.highest_note = tk.IntVar(value=self.cfg.highest_note)
        self._highest_spinbox = ttk.Spinbox(manual, from_=0, to=127, textvariable=self.highest_note,
                                            width=5, command=self._on_manual_range)
        self._highest_spinbox.pack(side="left")
        self.highest_name = ttk.Label(manual, text=_note_name(self.cfg.highest_note),
                                      foreground="#666", width=4)
        self.highest_name.pack(side="left", padx=4)

        self._midi_tip = ttk.Label(manual, text="", foreground="#666")
        self._midi_tip.pack(side="left", padx=(12, 0))
        self._setup_range_midi_listener()

        ttk.Label(f, text="Camera calibration").grid(row=4, column=0, sticky="w", **pad)
        self.calib_label = ttk.Label(f, text=self._calib_text())
        self.calib_label.grid(row=4, column=1, sticky="w", **pad)
        ttk.Button(f, text="(Re)calibrate corners...", command=self._calibrate_corners).grid(
            row=4, column=2, **pad)

        ttk.Label(f, text="Hands to track").grid(row=5, column=0, sticky="w", **pad)
        self.max_hands = tk.StringVar(value=str(self.cfg.max_hands))
        hands_row = ttk.Frame(f)
        hands_row.grid(row=5, column=1, sticky="w", **pad)
        for val, text in [("1", "1 (just one hand - lighter on CPU)"), ("2", "2 (both hands)")]:
            ttk.Radiobutton(hands_row, text=text, value=val, variable=self.max_hands).pack(
                anchor="w")

        ttk.Separator(f).grid(row=6, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(f, text="View while running").grid(row=7, column=0, sticky="w", **pad)
        self.view = tk.StringVar(value=self.cfg.default_view)
        for i, (val, text) in enumerate([("full", "Full (cinematic)"),
                                         ("plain", "Plain (debug HUD)"),
                                         ("none", "None (fastest - weak CPU)")]):
            ttk.Radiobutton(f, text=text, value=val, variable=self.view).grid(
                row=7 + i, column=1, sticky="w")

        self.draw_hands = tk.BooleanVar(value=self.cfg.draw_hand_skeleton)
        ttk.Checkbutton(f, text="Draw the hand skeleton overlay (turn off to save CPU on a "
                                "weaker machine - the keys, ribbons and finger dots stay)",
                       variable=self.draw_hands).grid(
            row=10, column=0, columnspan=3, sticky="w", padx=10, pady=(6, 0))

    def _on_manual_range(self):
        try:
            self.lowest_name.config(text=_note_name(int(self.lowest_note.get())))
            self.highest_name.config(text=_note_name(int(self.highest_note.get())))
        except (tk.TclError, ValueError):
            pass   # mid-keystroke

    # ---- click a range field, play that key, it fills in -----------
    # Non-blocking: polls rtmidi.get_message() (which never blocks - returns
    # None if nothing's waiting) on Tk's own event loop via .after(), so no
    # thread is needed. If the port's already open elsewhere (the main
    # engine, mid-session) opening it a second time can fail on some
    # backends - that's fine, this is a convenience on top of manual entry,
    # not a requirement, so it just quietly does nothing in that case.
    def _setup_range_midi_listener(self):
        self._midi_listener = None
        self._open_range_midi()
        self.after(30, self._poll_range_midi)   # the one poll chain for this window's lifetime

    def _open_range_midi(self):
        """(Re)acquire the MIDI input port for the click-a-field-then-play-it
        auto-fill. Separate from the poll-loop kickoff above so
        _detect_range/_calibrate_corners can release and reacquire around
        their own (main.py's) MIDI use without starting a second poll chain."""
        try:
            import rtmidi
            mi = rtmidi.MidiIn()
            ports = mi.get_ports()
            want = self.cfg.midi_in_match.lower()
            idx = next((i for i, n in enumerate(ports) if want and want in n.lower()),
                       0 if ports else None)
            if idx is not None:
                mi.open_port(idx)
                mi.ignore_types(sysex=True, timing=True, active_sense=True)
                self._midi_listener = mi
                self._midi_tip.config(text="tip: click a field, then press that key")
        except Exception:
            self._midi_listener = None   # no input, port busy, whatever - manual entry still works

    def _poll_range_midi(self):
        if not self.winfo_exists():
            return
        if self._midi_listener is not None:
            msg = self._midi_listener.get_message()
            if msg:
                data, _dt = msg
                if len(data) >= 3 and (data[0] & 0xF0) == 0x90 and data[2] > 0:
                    note = data[1]
                    focused = self.focus_get()
                    if focused is self._lowest_spinbox:
                        self.lowest_note.set(note)
                        self._on_manual_range()
                    elif focused is self._highest_spinbox:
                        self.highest_note.set(note)
                        self._on_manual_range()
        self.after(30, self._poll_range_midi)

    def _close_range_midi_listener(self):
        if self._midi_listener is not None:
            try:
                self._midi_listener.close_port()
            except Exception:
                pass
            self._midi_listener = None

    def _range_text(self):
        return f"{self.cfg.lowest_note} ({_note_name(self.cfg.lowest_note)}) - " \
               f"{self.cfg.highest_note} ({_note_name(self.cfg.highest_note)})"

    def _calib_text(self):
        return "calibrated" if CALIBRATION_PATH.exists() else "not calibrated yet"

    def _pick_camera(self):
        from main import pick_camera
        self.withdraw()
        try:
            pick_camera(self.cfg)
        except Exception as e:
            messagebox.showerror("Sleight", f"Couldn't open the camera preview:\n\n{e}\n\n"
                                 "If Sleight's already running with the camera on, that's "
                                 "usually why - close this window and press 'r' to "
                                 "recalibrate live instead.")
        finally:
            self.deiconify()
            self.camera_label.config(text=str(self.cfg.camera_index))

    def _sync_range_fields(self):
        """Push self.cfg's range into every widget that shows it - the
        read-only label and the manual Spinboxes both need to agree after
        anything changes cfg.lowest_note/highest_note directly, or a plain
        Save afterwards would silently overwrite the change with whatever
        the (now stale) Spinboxes still hold."""
        self.range_label.config(text=self._range_text())
        self.lowest_note.set(self.cfg.lowest_note)
        self.highest_note.set(self.cfg.highest_note)
        self._on_manual_range()

    def _detect_range(self):
        from main import _detect_key_range
        self._close_range_midi_listener()   # main.py needs the port to itself
        self.withdraw()
        result, errored = None, False
        try:
            result = _detect_key_range(self.cfg, seconds=15.0)
        except Exception as e:
            errored = True
            messagebox.showerror("Sleight", f"Key-range detection hit a problem:\n\n{e}")
        finally:
            self.deiconify()
            self._open_range_midi()
        if result and result[1] > result[0]:
            self.cfg.lowest_note, self.cfg.highest_note = result[0], result[1]
            self._sync_range_fields()
        elif not errored:
            messagebox.showinfo("Sleight", "No key range detected - keeping the current one.")

    def _calibrate_corners(self):
        from main import calibrate
        self._close_range_midi_listener()   # main.py's calibrate() also does key-range detection
        self.withdraw()
        try:
            calibrate(self.cfg)
        except Exception as e:
            messagebox.showerror("Sleight", f"Couldn't calibrate the camera:\n\n{e}\n\n"
                                 "If Sleight's already running with the camera on, that's "
                                 "usually why - close this window and press 'r' to "
                                 "recalibrate live instead.")
        finally:
            self.deiconify()
            self._open_range_midi()
            self._sync_range_fields()
            self.calib_label.config(text=self._calib_text())

    # ---- Gestures tab ------------------------------------------
    def _build_gesture_tab(self, f, pad):
        ttk.Label(f, text="Axis", font=("", 9, "bold")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Label(f, text="On", font=("", 9, "bold")).grid(row=0, column=1, **pad)
        ttk.Label(f, text="Sends", font=("", 9, "bold")).grid(row=0, column=2, **pad)
        ttk.Label(f, text="CC #", font=("", 9, "bold")).grid(row=0, column=3, **pad)
        ttk.Label(f, text="Invert", font=("", 9, "bold")).grid(row=0, column=4, **pad)
        sens_hdr = ttk.Frame(f)
        sens_hdr.grid(row=0, column=5, **pad)
        ttk.Label(sens_hdr, text="Travel for full effect", font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(sens_hdr, text="smaller = more sensitive", foreground="#666",
                 font=("", 8)).pack(anchor="w")

        self.axis_widgets = {}
        gmap = self.cfg.gesture_map
        for row, (key, label, desc) in enumerate(AXES, start=1):
            spec = gmap.get(key, {"target": "none"})
            target = spec.get("target", "none")

            name_cell = ttk.Frame(f)
            name_cell.grid(row=row, column=0, sticky="w", padx=10, pady=2)
            ttk.Label(name_cell, text=label).pack(anchor="w")
            ttk.Label(name_cell, text=desc, foreground="#666", font=("", 8)).pack(anchor="w")

            enabled = tk.BooleanVar(value=(target != "none"))
            ttk.Checkbutton(f, variable=enabled).grid(row=row, column=1, **pad)

            send_as = tk.StringVar(value="Pitch Bend" if target == "pitchbend" else "CC")
            send_box = ttk.Combobox(f, textvariable=send_as, values=["Pitch Bend", "CC"],
                                    width=10, state="readonly")
            send_box.grid(row=row, column=2, **pad)

            cc = tk.IntVar(value=int(spec.get("cc", 74 if key != "curl" else 1)))
            cc_box = ttk.Spinbox(f, from_=0, to=127, textvariable=cc, width=5)
            cc_box.grid(row=row, column=3, **pad)

            invert = tk.BooleanVar(value=bool(getattr(self.cfg, f"invert_{key}", False)))
            ttk.Checkbutton(f, variable=invert).grid(row=row, column=4, **pad)

            sens = tk.DoubleVar(value=float(getattr(self.cfg, f"{key}_full_scale")))
            ttk.Spinbox(f, from_=0.01, to=2.0, increment=0.01, textvariable=sens,
                       width=7).grid(row=row, column=5, **pad)

            def _sync_cc_state(send_as=send_as, cc_box=cc_box):
                cc_box.config(state="normal" if send_as.get() == "CC" else "disabled")
            send_as.trace_add("write", lambda *_a, fn=_sync_cc_state: fn())
            _sync_cc_state()

            self.axis_widgets[key] = dict(enabled=enabled, send_as=send_as, cc=cc,
                                          invert=invert, sens=sens)

        ttk.Label(f, text="\"Sends\" is what reaches the synth: Pitch Bend (per-note bend) "
                          "or a CC number you MIDI-learn at the synth end. Unticking On "
                          "turns that axis off entirely.",
                  foreground="#666", wraplength=520, justify="left").grid(
            row=len(AXES) + 1, column=0, columnspan=6, sticky="w", padx=10, pady=(10, 0))

    # ---- save / run --------------------------------------------
    def _apply_to_cfg(self):
        self.cfg.output_mode = self._output_mode_by_label.get(self.output_mode.get(), self.cfg.output_mode)
        self.cfg.midi_in_match = "" if self.midi_in.get().startswith("(auto") else self.midi_in.get()
        self.cfg.midi_out_match = self.midi_out.get()
        self.cfg.per_note_pitch_bend_range = int(self.bend_range.get())

        res = self.resolution.get().split(" ")[0]   # strip a trailing "(current)"
        w, h = (int(x) for x in res.split("x"))
        self.cfg.camera_width, self.cfg.camera_height = w, h
        self.cfg.default_view = self.view.get()
        self.cfg.draw_hand_skeleton = bool(self.draw_hands.get())
        self.cfg.max_hands = int(self.max_hands.get())

        lo, hi = int(self.lowest_note.get()), int(self.highest_note.get())
        if hi > lo:
            self.cfg.lowest_note, self.cfg.highest_note = lo, hi
        # hi <= lo silently keeps the previous range rather than saving a
        # broken one - the Spinboxes don't cross-validate against each other

        gmap = {}
        for key, _, _ in AXES:
            w_ = self.axis_widgets[key]
            if not w_["enabled"].get():
                gmap[key] = {"target": "none"}
            elif w_["send_as"].get() == "Pitch Bend":
                gmap[key] = {"target": "pitchbend"}
            else:
                gmap[key] = {"target": "cc", "cc": int(w_["cc"].get())}
            setattr(self.cfg, f"invert_{key}", bool(w_["invert"].get()))
            setattr(self.cfg, f"{key}_full_scale", float(w_["sens"].get()))
        self.cfg.gesture_map = gmap

    def _save(self):
        self._close_range_midi_listener()
        self._apply_to_cfg()
        self.cfg.save()
        self.result = False
        self.destroy()

    def _save_and_run(self):
        self._close_range_midi_listener()
        self._apply_to_cfg()
        self.cfg.save()
        self.result = True
        self.destroy()

    def _cancel(self):
        self._close_range_midi_listener()
        self.result = False
        self.destroy()


def run_settings(cfg: Config) -> bool:
    """Standalone entry point (`python main.py --settings`, no session
    already running): spin up a throwaway hidden root, show the settings
    window on top of it, block until closed. Returns True if the user
    clicked "Save & Run" - the caller should then start run(cfg, ...)."""
    root = tk.Tk()
    root.withdraw()
    _set_icon(root)
    _install_safe_callback_handler(root)
    win = SettingsWindow(root, cfg)
    root.wait_window(win)
    result = win.result
    root.destroy()
    return result


def open_full_settings(tk_state: dict, cfg: Config) -> bool:
    """In-session entry point (the 's' key while Sleight is running): reuse
    the run loop's shared hidden root (same tk_state dict as the UMP viewer
    below) instead of opening a second Tk root. Blocks this call - not the
    whole app - until the settings window closes, via wait_window rather
    than a nested mainloop. Returns True if "Save & Run" was clicked,
    meaning the caller should tear down and restart the session so a
    changed camera, hand count or key range actually takes effect."""
    if tk_state.get("root") is None:
        root = tk.Tk()
        root.withdraw()
        _set_icon(root)
        _install_safe_callback_handler(root)
        tk_state["root"] = root
    win = SettingsWindow(tk_state["root"], cfg)
    tk_state["root"].wait_window(win)
    return win.result


class GesturePanel(tk.Toplevel):
    """The lighter 's' panel: on/off, pitch-bend-or-CC, CC #, invert and
    sensitivity for each of glide/slide/curl - the same controls as
    SettingsWindow's Gestures tab, but every control applies the instant
    you touch it instead of waiting for Save & Run, because none of this
    needs the camera/tracking subsystem rebuilt the way a changed camera
    index or hand count does.

    That "instant" is only true because `expr_cfg` is the exact
    ExpressionConfig object every currently-held note's NoteExpression
    already shares (engine.py builds it once and hands the same instance
    to each), and `cfg.gesture_map` is the exact dict object engine.out
    already holds a reference to (engine.py passes it straight through at
    construction) - mutating both IN PLACE is what reaches the running
    engine. Replacing either with a freshly-built object here would just
    leave the engine holding the stale one, silently doing nothing."""

    def __init__(self, master, cfg: Config, expr_cfg):
        super().__init__(master)
        self.cfg = cfg
        self.expr_cfg = expr_cfg
        self.title("Sleight - Gesture Settings")
        self.resizable(False, False)

        pad = {"padx": 8, "pady": 6}
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True, padx=10, pady=10)

        headers = ["Axis", "On", "Sends", "CC #", "Invert", "Sensitivity"]
        for col, text in enumerate(headers):
            ttk.Label(f, text=text, font=("", 9, "bold")).grid(row=0, column=col, **pad)

        self.axis_widgets = {}
        gmap = self.cfg.gesture_map
        for row, (key, label, desc) in enumerate(AXES, start=1):
            spec = gmap.get(key, {"target": "none"})
            target = spec.get("target", "none")

            name_cell = ttk.Frame(f)
            name_cell.grid(row=row, column=0, sticky="w", padx=8, pady=2)
            ttk.Label(name_cell, text=label).pack(anchor="w")
            ttk.Label(name_cell, text=desc, foreground="#666", font=("", 8)).pack(anchor="w")

            enabled = tk.BooleanVar(value=(target != "none"))
            ttk.Checkbutton(f, variable=enabled).grid(row=row, column=1, **pad)

            send_as = tk.StringVar(value="Pitch Bend" if target == "pitchbend" else "CC")
            ttk.Combobox(f, textvariable=send_as, values=["Pitch Bend", "CC"],
                        width=10, state="readonly").grid(row=row, column=2, **pad)

            cc = tk.IntVar(value=int(spec.get("cc", 74 if key != "curl" else 1)))
            cc_box = ttk.Spinbox(f, from_=0, to=127, textvariable=cc, width=5)
            cc_box.grid(row=row, column=3, **pad)

            invert = tk.BooleanVar(value=bool(getattr(self.cfg, f"invert_{key}", False)))
            ttk.Checkbutton(f, variable=invert).grid(row=row, column=4, **pad)

            sens = tk.DoubleVar(value=float(getattr(self.expr_cfg, f"{key}_full_scale")))
            ttk.Spinbox(f, from_=0.01, to=2.0, increment=0.01, textvariable=sens,
                       width=7).grid(row=row, column=5, **pad)

            self.axis_widgets[key] = dict(enabled=enabled, send_as=send_as, cc=cc,
                                          invert=invert, sens=sens)
            self._wire_axis_live(key, gmap, cc_box, enabled, send_as, cc, invert, sens)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(btns, text="changes apply instantly - nothing to save unless you\n"
                             "want it to survive the next launch too",
                 foreground="#666", font=("", 8), justify="left").pack(side="left")
        ttk.Button(btns, text="Save to config.json", command=self._save).pack(side="right")
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right", padx=6)

    def _wire_axis_live(self, key, gmap, cc_box, enabled, send_as, cc, invert, sens):
        def apply(*_a):
            cc_box.config(state="normal" if send_as.get() == "CC" else "disabled")
            if not enabled.get():
                gmap[key] = {"target": "none"}
            elif send_as.get() == "Pitch Bend":
                gmap[key] = {"target": "pitchbend"}
            else:
                try:
                    cc_val = int(cc.get())
                except (tk.TclError, ValueError):
                    return   # mid-keystroke - leave the last good value in place
                gmap[key] = {"target": "cc", "cc": cc_val}

            setattr(self.cfg, f"invert_{key}", bool(invert.get()))
            setattr(self.expr_cfg, f"invert_{key}", bool(invert.get()))

            try:
                sens_val = float(sens.get())
            except (tk.TclError, ValueError):
                return
            setattr(self.cfg, f"{key}_full_scale", sens_val)
            setattr(self.expr_cfg, f"{key}_full_scale", sens_val)

        for var in (enabled, send_as, cc, invert, sens):
            var.trace_add("write", apply)
        apply()   # sync cc_box's initial enabled/disabled state

    def _save(self):
        self.cfg.save()


def open_gesture_panel(tk_state: dict, cfg: Config, expr_cfg) -> None:
    """In-session entry point (the 's' key). Non-blocking, same pattern as
    the UMP viewer below - stays open alongside the running view so you can
    tweak feel without interrupting play. A second 's' press just focuses
    the existing panel instead of opening a duplicate. `tk_state["panel"]`
    (per-frame close detection, and refocusing Sleight's own window when it
    closes) is handled generically already, in _run_session's main loop -
    the same code path that already covers the UMP viewer."""
    if tk_state.get("root") is None:
        root = tk.Tk()
        root.withdraw()
        _set_icon(root)
        tk_state["root"] = root
    panel = tk_state.get("panel")
    if panel is not None and panel.winfo_exists():
        panel.lift()
        panel.focus_force()
        return
    tk_state["panel"] = GesturePanel(tk_state["root"], cfg, expr_cfg)


def pump(tk_state: dict):
    """Call once per frame from the run loop - keeps the shared hidden root
    (and whatever's open on it, e.g. the UMP viewer) responsive. Cheap no-op
    while nothing has opened it yet."""
    root = tk_state.get("root")
    if root is not None:
        root.update()


# ---------------------------------------------------------------------------
# MIDI 2.0 UMP viewer - tails session.midi2.log and shows it live, decoded
# and colour-coded, instead of a wall of hex text in Notepad. This is the
# thing that actually demonstrates the project's MIDI 2.0 claim: DAWs won't
# take raw UMP over a port, but here's the real 32-bit-resolution stream,
# live, while you play.
#
# It tails the *file*, not the Engine - no coupling to the running session at
# all, so it works exactly the same launched standalone (--ump-viewer,
# watching a log from a previous run, or from another Sleight process writing
# to the same file) as it does opened with 'u' mid-session.
# ---------------------------------------------------------------------------
_TAG_COLORS = {
    "noteon": "#7CFC7C", "noteoff": "#B0876B", "bend": "#FFA64D",
    "slide": "#4DA6FF", "curl": "#C58CFF", "other": "#AAAAAA",
}


def _classify_ump_line(line: str) -> str:
    if "note on" in line:
        return "noteon"
    if "note off" in line:
        return "noteoff"
    if "per-note bend" in line:
        return "bend"
    if "per-note slide" in line:
        return "slide"
    if "per-note curl" in line:
        return "curl"
    return "other"


class UmpViewer(tk.Toplevel):
    POLL_MS = 200
    MAX_LINES = 1500

    def __init__(self, master, cfg: Config):
        super().__init__(master)
        self.log_path = cfg.resolved_ump_log_path()
        self.title("Sleight - MIDI 2.0 UMP Viewer")
        self.geometry("780x420")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        self.show_stream = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="show continuous bend/slide/curl (busy - good for a demo)",
                       variable=self.show_stream).pack(side="left")
        ttk.Label(top, text="filter:").pack(side="left", padx=(16, 4))
        self.filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter_var, width=18).pack(side="left")
        ttk.Button(top, text="Clear", command=self._clear).pack(side="right")

        self.text = tk.Text(self, bg="#0e0e12", fg="#cccccc", insertbackground="#cccccc",
                            font=("Consolas", 9), wrap="none", state="disabled")
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for tag, color in _TAG_COLORS.items():
            self.text.tag_configure(tag, foreground=color)

        self._fh = None
        self._pos = 0
        self._open_log()
        self._poll()

    def _open_log(self):
        try:
            if self.log_path.exists():
                self._fh = open(self.log_path, "r", encoding="utf-8", errors="replace")
                self._fh.seek(0, 2)      # tail: start at the current end, not the whole history
                self._pos = self._fh.tell()
                self._insert_line(f"--- watching {self.log_path} ---\n", "other")
            else:
                self._insert_line(f"--- no log yet at {self.log_path} - waiting for Sleight "
                                  f"to run (write_ump_log must be on) ---\n", "other")
        except OSError as e:
            self._insert_line(f"--- couldn't open log: {e} ---\n", "other")

    def _insert_line(self, line: str, tag: str):
        at_bottom = self.text.yview()[1] >= 0.999
        self.text.config(state="normal")
        self.text.insert("end", line, tag)
        n_lines = int(self.text.index("end-1c").split(".")[0])
        if n_lines > self.MAX_LINES:
            self.text.delete("1.0", f"{n_lines - self.MAX_LINES}.0")
        self.text.config(state="disabled")
        if at_bottom:
            self.text.see("end")

    def _poll(self):
        if self._fh is None:
            self._open_log()
        else:
            try:
                self._fh.seek(0, 2)
                end = self._fh.tell()
                if end < self._pos:              # file was truncated - a new session started
                    self._pos = 0
                    self._insert_line("--- log restarted ---\n", "other")
                self._fh.seek(self._pos)
                new_lines = self._fh.readlines()
                self._pos = self._fh.tell()
                fil = self.filter_var.get().strip().lower()
                for line in new_lines:
                    if line.startswith("#") or not line.strip():
                        continue
                    kind = _classify_ump_line(line)
                    if kind in ("bend", "slide", "curl") and not self.show_stream.get():
                        continue
                    if fil and fil not in line.lower():
                        continue
                    self._insert_line(line, kind)
            except OSError:
                self._fh = None
        self.after(self.POLL_MS, self._poll)

    def _clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")


def open_ump_viewer(tk_state: dict, cfg: Config):
    """Same tk_state dict as open_full_settings above - shares the one hidden Tk root
    a process is allowed. A second 'u' press focuses the existing viewer."""
    if tk_state.get("root") is None:
        root = tk.Tk()
        root.withdraw()
        _set_icon(root)
        _install_safe_callback_handler(root)
        tk_state["root"] = root
    viewer = tk_state.get("ump_viewer")
    if viewer is not None and viewer.winfo_exists():
        viewer.lift()
        viewer.focus_force()
        return
    tk_state["ump_viewer"] = UmpViewer(tk_state["root"], cfg)


def run_ump_viewer_standalone(cfg: Config):
    """--ump-viewer: just the viewer, no camera/MIDI/tracking. Blocks until
    the window is closed."""
    root = tk.Tk()
    root.withdraw()
    _set_icon(root)
    _install_safe_callback_handler(root)
    UmpViewer(root, cfg)
    root.mainloop()
