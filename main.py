"""
Sleight - webcam per-note expression for any MIDI keyboard.

    python main.py                 run it (auto-calibrates on first launch)
    python main.py --settings      settings window: ports, camera, view, gesture map
    python main.py --ump-viewer    live MIDI 2.0 UMP log viewer, standalone
    python main.py --list-ports    show MIDI port names
    python main.py --pick-camera   got more than one webcam? preview + choose which
    python main.py --pick-midi-input   got more than one MIDI input? play a key to pick which
    python main.py --calibrate     key range (play lowest+highest) + camera corners
    python main.py --midi-monitor  just re-check your key range, without recalibrating
    python main.py --view plain    flat debug HUD instead of the visualiser
    python main.py --view none     skip drawing entirely - fastest, for a weak CPU
    python main.py --dry-run       run with no MIDI out port (tracking only)
    python main.py --selftest      headless pipeline check, no camera or MIDI

While running:  q quit   v cycle view   r re-calibrate
                s settings (MIDI, camera, hands, key range, gestures -
                  caps or not, same key either way; restarts on Save & Run)
                u MIDI 2.0 UMP viewer
"""
from __future__ import annotations

import argparse
import collections
import statistics
import sys
import time

import cv2
import numpy as np

from calibration import Calibration, run_calibration
from config import CALIBRATION_PATH, CONFIG_PATH, Config
from camera import Camera
from engine import Engine
from hud import draw_hud
from visualizer import Visualizer
import ump

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _note_name(n: int) -> str:
    return f"{_NOTE_NAMES[n % 12]}{n // 12 - 1}"


def _open_camera(cfg: Config) -> Camera:
    return Camera(cfg.camera_index, cfg.camera_width, cfg.camera_height)


# ---------------------------------------------------------------------------
# setup helpers
# ---------------------------------------------------------------------------
def list_ports():
    import rtmidi
    print("MIDI INPUT ports (your keyboard):")
    for i, n in enumerate(rtmidi.MidiIn().get_ports()):
        print(f"  [{i}] {n}")
    outs = rtmidi.MidiOut().get_ports()
    print("MIDI OUTPUT ports (your DAW listens on one of these):")
    for i, n in enumerate(outs):
        print(f"  [{i}] {n}")
    if not any("sleight" in n.lower() or "loopmidi" in n.lower() for n in outs):
        print("  -> no loopMIDI/Sleight port yet. Install loopMIDI, add one named 'Sleight'.")


def _detect_key_range(cfg: Config, seconds: float = 15.0):
    """Listen on the MIDI input for `seconds` and return (lowest, highest,
    count), or None if there's no input port or nothing came in. Shared by
    --midi-monitor (just reports) and --calibrate (also saves it)."""
    import rtmidi
    mi = rtmidi.MidiIn()
    ports = mi.get_ports()
    want = cfg.midi_in_match.lower()
    idx = next((i for i, n in enumerate(ports) if want and want in n.lower()),
               0 if ports else None)
    if idx is None:
        print("  no MIDI input port found - skipping key-range detection.")
        return None

    mi.open_port(idx)
    print(f"  listening on {ports[idx]} for {seconds:g}s - "
          f"play your LOWEST key, then your HIGHEST.")
    lo, hi, count = 200, -1, 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        m = mi.get_message()
        if m and (m[0][0] & 0xF0) == 0x90 and m[0][2] > 0:
            n = m[0][1]
            lo, hi, count = min(lo, n), max(hi, n), count + 1
            print(f"    {n} ({_note_name(n)})   range so far {lo}..{hi}")
        time.sleep(0.004)
    mi.close_port()
    return (lo, hi, count) if hi >= 0 else None


def midi_monitor(cfg: Config, seconds: float = 25.0):
    """Report the key range without touching config.json - --calibrate does
    this same detection and saves it, so this is really just for a re-check."""
    result = _detect_key_range(cfg, seconds)
    if result is None:
        print("\nNo notes received - is the keyboard on and connected?")
        return
    lo, hi, count = result
    print(f"\nlowest_note = {lo} ({_note_name(lo)})   "
          f"highest_note = {hi} ({_note_name(hi)})   ({count} notes)")


def calibrate(cfg: Config):
    print("Step 1/2 - key range: play your lowest key, then your highest.")
    result = _detect_key_range(cfg, seconds=15.0)
    if result is None:
        print("  keeping the existing range in config.json.")
    else:
        lo, hi, _ = result
        if hi > lo:
            cfg.lowest_note, cfg.highest_note = lo, hi
            cfg.save()
            print(f"  saved lowest_note={lo} ({_note_name(lo)})  "
                  f"highest_note={hi} ({_note_name(hi)}) -> {CONFIG_PATH.name}")
        else:
            print("  only heard one key - keeping the existing range in config.json.")

    print("\nStep 2/2 - camera: click the 4 corners of the key bed.")
    cap = _open_camera(cfg)
    try:
        calib = run_calibration(cap, CALIBRATION_PATH, cfg.flip_horizontal)
        if calib is None:
            print("  cancelled - camera calibration unchanged.")
        else:
            print(f"  saved -> {CALIBRATION_PATH.name}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def pick_camera(cfg: Config, max_index: int = 5):
    """For a laptop with a built-in webcam plus an external one: preview each
    camera index in turn so you can tell them apart by eye, then save the
    pick into config.json. ENTER = use this one, any other key = next camera,
    Esc = cancel without changing anything.

    Known issue: a second camera wasn't selectable. Most likely cause -
    DirectShow (the default backend on Windows, chosen for its normally
    better multi-camera enumeration) sometimes can't open a particular
    external UVC webcam that Media Foundation opens fine, or vice versa.
    Previously a failed index was silently skipped with zero explanation, so
    from the outside "can't select the second camera" and "the second camera
    never even opens" looked identical. Now: try DSHOW, retry once with MSMF
    if that fails, and print exactly what happened either way."""
    win = "Sleight - pick your camera  (ENTER = use this one, any key = next, Esc = cancel)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.moveWindow(win, 40, 40)
    chosen = None
    try:
        for idx in range(max_index):
            cam = None
            for backend, name in ((cv2.CAP_DSHOW, "DirectShow"), (cv2.CAP_MSMF, "Media Foundation")):
                try:
                    cam = Camera(idx, 640, 480, backend=backend)
                    break
                except Exception:
                    continue
            if cam is None:
                print(f"  camera {idx}: nothing here (tried DirectShow and Media "
                      f"Foundation) - trying the next index.")
                continue
            print(f"  camera {idx} ({name}): showing preview - ENTER to pick it, "
                  f"any other key for the next one, Esc to cancel.")
            try:
                while True:
                    ok, frame = cam.read()
                    if ok:
                        if cfg.flip_horizontal:
                            frame = cv2.flip(frame, 1)
                        cv2.putText(frame, f"camera index {idx}", (16, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)
                        cv2.imshow(win, frame)
                    if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                        print("  window closed - cancelled, camera_index unchanged.")
                        return
                    k = cv2.waitKey(30) & 0xFF
                    if k == 13:                  # Enter
                        chosen = idx
                        break
                    if k == 27:                  # Esc
                        print("  cancelled - camera_index unchanged.")
                        return
                    if k != 255:                 # any real key = next camera
                        break
            finally:
                cam.release()
                time.sleep(0.15)   # give the driver a moment to actually let go
                                   # of the device before the next index tries it
            if chosen is not None:
                break
    finally:
        cv2.destroyWindow(win)
    if chosen is None:
        print(f"  no camera picked (checked indices 0..{max_index - 1}) - "
              f"camera_index unchanged.")
        return
    cfg.camera_index = chosen
    cfg.save()
    print(f"  saved camera_index={chosen} -> {CONFIG_PATH.name}")


def pick_midi_input(cfg: Config, listen_seconds: float = 15.0):
    """Listen on every MIDI input port at once and use whichever one actually
    sends a note - there's no camera-style preview possible for a MIDI port
    (nothing to look at, just a name), so "play the keyboard you mean" is the
    friendliest way to identify it, especially for someone who doesn't know
    or care what their interface is called in Windows.

    This is the step a first real setup used to miss: with only
    one device plugged in, config.json's default (midi_in_match = "", i.e.
    "first port seen") just happens to work - but the moment there's a
    second MIDI input on the system (a DAW's own virtual port, a loopback,
    anything), "first port" can silently be the wrong one, with nothing on
    screen to say so. The only fix was hand-editing config.json; this
    asks up front instead. It also matters before
    calibrate()'s own key-range detection runs (first-run calls both) -
    that detection listens on midi_in_match too, so getting the port right
    first is what lets it hear anything at all.

    No prompt at all if there's only one port (the common case) or none
    (nothing to pick). With more than one: play a key within the time
    window and that port wins; nothing played falls back to a typed choice
    from a numbered list, same spirit as pick_camera's Esc-to-skip."""
    import rtmidi
    ports = rtmidi.MidiIn().get_ports()
    if not ports:
        print("  no MIDI input ports seen - plug in your keyboard, then "
              "--pick-midi-input (or Settings) once it's connected.")
        return
    if len(ports) == 1:
        cfg.midi_in_match = ports[0]
        cfg.save()
        print(f"  only one MIDI input seen - using it: {ports[0]}")
        return

    print(f"  {len(ports)} MIDI inputs seen - play a key on YOUR keyboard now "
          f"to identify it ({listen_seconds:g}s):")
    for i, n in enumerate(ports):
        print(f"    [{i}] {n}")

    listeners = []
    try:
        for i, name in enumerate(ports):
            mi = rtmidi.MidiIn()
            try:
                mi.open_port(i)
                mi.ignore_types(sysex=True, timing=True, active_sense=True)
                listeners.append((i, name, mi))
            except Exception:
                continue   # already open elsewhere - just can't listen on it here

        end = time.monotonic() + listen_seconds
        while time.monotonic() < end:
            for i, name, mi in listeners:
                msg = mi.get_message()
                if msg and (msg[0][0] & 0xF0) == 0x90 and msg[0][2] > 0:
                    cfg.midi_in_match = name
                    cfg.save()
                    print(f"  got a note from [{i}] {name} - using it.")
                    return
            time.sleep(0.004)
    finally:
        for _, _, mi in listeners:
            mi.close_port()

    try:
        choice = input(f"  no note seen - type a port number (0-{len(ports) - 1}), "
                        f"or Enter for [0]: ").strip()
        idx = int(choice) if choice else 0
    except ValueError:
        idx = 0
    idx = max(0, min(len(ports) - 1, idx))
    cfg.midi_in_match = ports[idx]
    cfg.save()
    print(f"  using [{idx}] {ports[idx]}")


# ---------------------------------------------------------------------------
# the run loop
# ---------------------------------------------------------------------------
class _RestartWithNewSettings(Exception):
    """Raised by the 's' key when the in-session settings window closed with
    Save & Run clicked. Caught in run() to tear down the current camera/
    engine/window and set back up with whatever changed - camera, hand
    count, key range, view - without the user ever touching a command line."""


def run(cfg: Config, dry_run: bool = False, view: str | None = None):
    """view: "full" (the cinematic visualiser), "plain" (flat debug HUD),
    or "none" (skip drawing entirely - fastest, for a weak CPU). None (the
    normal case) means "use cfg.default_view" - re-read on every restart, so
    choosing a different view in Settings and clicking Save & Run actually
    takes effect. (It used to be resolved once at launch and reused for every
    restart, so Plain/None in Settings silently kept showing the full view.)
    An explicit --view on the command line still wins for the whole run.

    Loops on _RestartWithNewSettings so the in-session settings window can
    change anything - including things like camera index or hand count that
    need their subsystem rebuilt, not hot-swapped - and have it take effect
    immediately, still with zero command line involved."""
    tk_state = {"root": None, "panel": None, "ump_viewer": None}
    try:
        while True:
            try:
                _run_session(cfg, dry_run, view or cfg.default_view, tk_state)
                return
            except _RestartWithNewSettings:
                continue   # cfg was already updated in place by the settings window
    finally:
        if tk_state["root"] is not None:
            tk_state["root"].destroy()


def _run_session(cfg: Config, dry_run: bool, view: str, tk_state: dict):
    plain = view == "plain"
    no_view = view == "none"

    if not CALIBRATION_PATH.exists():
        # First launch, most likely a double-click with no calibration.json
        # sitting next to the exe yet. Printing a hint and exiting just flashes
        # a console window shut before anyone can read it - walk through setup
        # instead, then carry straight on into the run.
        #
        # Bug fixed here: this used to go straight into calibrate(), which
        # opens whatever camera_index is already in config.json (default 0)
        # with no chance to choose - anyone with more than one camera (a
        # laptop's built-in plus an external one mounted over the keys, the
        # exact setup this whole project assumes) could get calibration
        # pointed at the wrong one on their very first run, with no way to
        # fix it from this flow. pick_camera() first, every time, so the
        # camera is confirmed - not just assumed - before anything else.
        print("First run - no calibration yet. Let's set it up.\n")
        print("Step 0 - camera: ENTER to use the one shown, any other key for "
              "the next one, Esc to skip and keep the default.")
        pick_camera(cfg)
        print()
        print("Step 0.5 - MIDI keyboard: play a key to identify which input is yours.")
        pick_midi_input(cfg)
        print()
        calibrate(cfg)
        print()
        if not CALIBRATION_PATH.exists():
            print("Calibration was cancelled, so there's nothing to run yet. "
                  "Try again with --calibrate when you're ready.")
            return

    calib = Calibration.load(CALIBRATION_PATH)
    # Windows can renumber cameras between boots (virtual cameras, phones, USB
    # devices coming and going), so the saved index can quietly start pointing
    # at a different one - say which it is, and where to fix it.
    print(f"Camera: index {cfg.camera_index}  (wrong one? press 's' > Camera & Calibration > "
          f"Preview & pick camera)")
    cap = _open_camera(cfg)
    engine = Engine(cfg, calib, dry_run=dry_run)
    if not engine.open_midi_in() and not dry_run:
        print("(no MIDI input - tracking will run but nothing plays)")

    # view="none": tracking + MIDI run exactly the same, we just never build
    # the cinematic frame (that compositing is the expensive part, not
    # mediapipe - on a weak CPU it's most of your frame time). A tiny
    # placeholder window stays open so q/hotkeys still work.
    viz = None if no_view else Visualizer(engine.geom, mode="stage", draw_hands=cfg.draw_hand_skeleton)
    placeholder = None
    if no_view:
        win = "Sleight - view hidden (click here, then q to quit)"
        placeholder = np.zeros((180, 480, 3), np.uint8)
        cv2.putText(placeholder, "Sleight is running - view hidden for speed",
                    (14, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(placeholder, "click this window, then:",
                    (14, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1, cv2.LINE_AA)
        cv2.putText(placeholder, "s settings   u UMP viewer   q quit",
                    (14, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1, cv2.LINE_AA)
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 480, 180)
    else:
        win = "Sleight - per-note expression for any keyboard"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 1280, 720)
    cv2.moveWindow(win, 40, 40)          # OpenCV can restore an off-screen position

    perf = collections.deque(maxlen=60)
    last = time.monotonic()
    last_perf_print = last
    icon_done = False
    popup_was_open = False   # tracks the UMP viewer specifically - see below
    from settings_gui import pump

    try:
        while True:
            pump(tk_state)   # keep the shared hidden Tk root (e.g. the UMP viewer) responsive

            # the UMP viewer is non-blocking (stays open alongside the main
            # view, unlike settings which pauses this loop until closed) -
            # so its own close has to be noticed here, per frame, rather
            # than right after a function call the way 's' does it above.
            root = tk_state.get("root")
            popup_open = root is not None and len(root.winfo_children()) > 0
            if popup_was_open and not popup_open:
                _focus_window(win)
            popup_was_open = popup_open

            ok, frame = cap.read()
            if not ok:
                break
            if cfg.flip_horizontal:
                frame = cv2.flip(frame, 1)

            now = time.monotonic()
            dt, last = now - last, now

            t0 = time.monotonic()
            tips, tips_kb = engine.step(frame, dt)
            t1 = time.monotonic()

            if no_view:
                out_img = placeholder
            elif plain:
                draw_hud(frame, engine, tips, tips_kb)
                out_img = frame
            else:
                out_img = viz.render(frame, engine, tips, engine.tracker.last_hands)

            # Bug fixed here: clicking the window's X reopened it. cv2.imshow()
            # silently RECREATES a window if it's been closed since the last
            # call - so this has to be checked before imshow runs again this
            # frame, not after. Checking after (as it was) meant imshow had
            # already resurrected the window by the time the check ran, so
            # a closed window was never actually seen as closed.
            if icon_done and cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                break

            cv2.imshow(win, out_img)
            t2 = time.monotonic()

            if not icon_done:
                cv2.waitKey(1)
                cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)   # yank it to the front once
                cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 0)
                _set_window_icon(win)
                icon_done = True

            perf.append((t1 - t0, t2 - t1, t2 - now))
            if now - last_perf_print > 2.0 and perf:
                track, draw, loop = (1000 * statistics.mean(x) for x in zip(*perf))
                print(f"  perf: track {track:4.0f}ms  draw {draw:4.0f}ms  "
                      f"loop {loop:4.0f}ms  ({1000 / max(1, loop):.0f} fps)")
                last_perf_print = now

            if not _handle_key(cv2.waitKey(1) & 0xFF, engine, viz, cap, cfg, win, tk_state):
                break
    finally:
        engine.close()
        cap.release()
        cv2.destroyAllWindows()
        # tk_state's hidden root is owned by run() (it needs to survive a
        # restart) - not torn down here.


def _handle_key(k, engine, viz, cap, cfg, win, tk_state) -> bool:
    """Return False to quit the loop. Can also raise _RestartWithNewSettings
    (from 's') - deliberately not caught here, it's meant to propagate up
    through run()'s try/finally so the session tears down cleanly first."""
    if k in (ord('q'), 27):
        return False
    elif k == ord('v') and viz is not None:
        viz.cycle_mode()
    elif k in (ord('s'), ord('S')):
        # One key, caps or not - checking both keycodes here means whichever
        # of Caps Lock or physical Shift you happened to have on no longer
        # decides anything; there used to be a second, case-sensitive
        # hotkey routing capital S somewhere else, which was exactly the
        # inconsistency users noticed, on top of a real crash. That crash was
        # _build_midi_tab() in settings_gui.py calling rtmidi's port list
        # with no error handling (every other rtmidi call in that file was
        # already defensively wrapped) - fixed there now, and confirmed
        # rendering correctly standalone before restoring this hotkey.
        from settings_gui import open_full_settings
        try:
            result = open_full_settings(tk_state, cfg)   # blocks until the window closes
        except Exception as e:
            # A bug in the settings UI (a tab, a widget) used to take the
            # whole live session down with it - mid-performance, that's the
            # worst possible time to lose everything. Print it and keep
            # playing; nothing here has touched cfg on disk, so nothing's lost.
            print(f"(settings window hit an error and was closed: {e})")
            result = False
        _focus_window(win)                            # give keyboard focus back to Sleight
        if result:                                    # True = Save & Run clicked
            raise _RestartWithNewSettings()
    elif k == ord('u'):
        from settings_gui import open_ump_viewer
        open_ump_viewer(tk_state, cfg)   # non-blocking, stays open alongside -
                                          # focus is restored when it's closed, tracked
                                          # per-frame in _run_session (it doesn't block here)
    elif k == ord('p'):
        engine.out.next_patch()
    elif k == ord('P'):
        engine.out.prev_patch()
    elif k == ord('e'):
        engine.out.show_editor()
    elif k == ord('r'):
        cv2.destroyWindow(win)
        new_calib = run_calibration(cap, CALIBRATION_PATH, cfg.flip_horizontal)
        if new_calib is not None:            # None = cancelled - keep the old one
            engine.calib = new_calib
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    return True


def _set_window_icon(win_title: str):
    """Give the OpenCV window our icon instead of the default. Windows only,
    best-effort - a wrong icon isn't worth crashing over."""
    if sys.platform != "win32":
        return
    ico = CALIBRATION_PATH.parent / "icon.ico"
    if not ico.exists():
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, win_title)
        if not hwnd:
            return
        for size, which in ((32, 1), (16, 0)):          # ICON_BIG, ICON_SMALL
            h = u.LoadImageW(None, str(ico), 1, size, size, 0x10)  # LR_LOADFROMFILE
            if h:
                u.SendMessageW(hwnd, 0x0080, which, h)   # WM_SETICON
    except Exception:
        pass


def _focus_window(win_title: str):
    """Known issue: close a popup (settings, UMP viewer) and the main
    window doesn't reactivate - hotkeys stop responding because cv2.waitKey
    only sees keypresses when its own window actually has OS input focus,
    and Windows doesn't hand focus back to whichever window had it before a
    Tk popup on its own. Windows only, best-effort."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, win_title)
        if hwnd:
            u.ShowWindow(hwnd, 9)          # SW_RESTORE, in case it got minimised
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# selftest - runs the binding/expression/output/UMP path on synthetic data
# ---------------------------------------------------------------------------
def selftest(cfg: Config):
    print("selftest: building engine (dry-run MIDI, no camera)...")
    calib = Calibration(np.eye(3, dtype=np.float32), (cfg.camera_width, cfg.camera_height))
    eng = Engine(cfg, calib, dry_run=True)
    geom = eng.geom

    # two fingers: one on middle C, one on the E above
    def place(offset_c=0.0):
        uc, ue = geom.note_to_u(60), geom.note_to_u(64)
        eng._tips_kb = [(1, uc + offset_c, 0.5, "I"), (2, ue, 0.5, "M")]
        return {1: (uc + offset_c, 0.5, "I"), 2: (ue, 0.5, "M")}

    place()
    eng._note_on(60, 100)
    eng._note_on(64, 90)
    assert eng.binder.bindings[60].anchored, "C did not bind to a finger"
    assert eng.binder.bindings[64].anchored, "E did not bind to a finger"
    print(f"  bind OK: C -> {eng.binder.bindings[60].finger_label}   "
          f"E -> {eng.binder.bindings[64].finger_label}")

    # wiggle only C's finger sideways
    for i in range(30):
        eng.binder.update(place(offset_c=0.03 * np.sin(i / 3.0)))
        for b in eng.binder.active():
            eng.expr[b.note].update(b.du, b.dv, b.dcurl, 1 / 60)
    gc, ge = eng.expr[60].glide, eng.expr[64].glide
    print(f"  after wiggle: C glide={gc:+.3f}   E glide={ge:+.3f}")
    assert abs(gc) > 0.05, "C glide should have moved"
    assert abs(ge) < 1e-6, "E glide should be untouched - notes must be independent"

    # curl only C's finger
    eng.binder.bindings[60].curl0 = eng.binder.bindings[64].curl0 = 0.1
    for _ in range(30):
        eng.binder.update({1: (geom.note_to_u(60), 0.5, "I"), 2: (geom.note_to_u(64), 0.5, "M")},
                          {1: 0.45, 2: 0.1})
        for b in eng.binder.active():
            eng.expr[b.note].update(b.du, b.dv, b.dcurl, 1 / 60)
    cc, ce = eng.expr[60].curl, eng.expr[64].curl
    print(f"  after curl:   C curl={cc:+.3f}   E curl={ce:+.3f}")
    assert abs(cc) > 0.1, "C curl should have moved"
    assert abs(ce) < 1e-6, "E curl should be untouched"
    eng.out.set_expression(60, "curl", cc)     # exercise the output path

    # UMP word shape: message type 0x4, status 0x6 (per-note pitch bend)
    w = ump.per_note_pitch_bend(0, 3, 60, ump.bipolar_to_u32(0.5))
    assert (w[0] >> 28) == 0x4 and ((w[0] >> 20) & 0xF) == 0x6, "bad UMP word0"
    print(f"  UMP per-note bend: {w[0]:08X} {w[1]:08X}")

    eng._note_off(60)
    eng._note_off(64)
    eng.close()
    print("selftest PASSED")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sleight - webcam per-note MIDI expression")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--midi-monitor", action="store_true",
                    help="re-check your key range without recalibrating the camera")
    ap.add_argument("--calibrate", action="store_true",
                    help="key range + camera corners; saves both to config.json")
    ap.add_argument("--pick-camera", action="store_true",
                    help="preview each webcam and choose which one to use")
    ap.add_argument("--pick-midi-input", action="store_true",
                    help="play a key on your keyboard to identify which MIDI input is yours")
    ap.add_argument("--view", choices=["full", "plain", "none"], default=None,
                    help="full = cinematic, plain = flat debug HUD, "
                         "none = skip drawing entirely (fastest, for a weak CPU). "
                         "Defaults to config.json's default_view (itself \"full\" "
                         "unless you've changed it in --settings).")
    ap.add_argument("--settings", action="store_true",
                    help="open the settings window instead of running")
    ap.add_argument("--ump-viewer", action="store_true",
                    help="open just the live MIDI 2.0 UMP log viewer")
    ap.add_argument("--dry-run", action="store_true", help="run with no MIDI out port")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config.load()
    if args.list_ports:
        list_ports()
    elif args.midi_monitor:
        midi_monitor(cfg)
    elif args.pick_camera:
        pick_camera(cfg)
    elif args.pick_midi_input:
        pick_midi_input(cfg)
    elif args.calibrate:
        calibrate(cfg)
    elif args.settings:
        from settings_gui import run_settings
        if run_settings(cfg):                # True = user clicked "Save & Run"
            run(cfg, dry_run=args.dry_run, view=args.view)
    elif args.ump_viewer:
        from settings_gui import run_ump_viewer_standalone
        run_ump_viewer_standalone(cfg)
    elif args.selftest:
        selftest(cfg)
    else:
        run(cfg, dry_run=args.dry_run, view=args.view)


if __name__ == "__main__":
    main()
