# Sleight — manual

Sleight watches your hands with a webcam and adds per-note expression to an
ordinary MIDI keyboard. Hold a note and move the finger that's holding it:
slide it sideways to bend that one note, forward and back for timbre, curl it
for a third control. Every note of a chord is shaped on its own.

By default it sends the result as **MPE** on a virtual MIDI port, so in your
DAW it looks like any other MIDI controller — no sound engine of its own, you
pick the synth. It can also send genuine live **MIDI 2.0** (real UMP, not the
MPE workaround) over Windows MIDI Services; see §3 and §9 for that path. Most
people should start with MPE — it needs no extra install and everything
already understands it.

If you just want to get going, read `QUICKSTART.md` instead. This is the long
version, with every setting and the things that go wrong.

---

## 1. What you need

- A MIDI keyboard. Anything class-compliant — on Windows there's no driver to
  install. MIDI 1.0 is fine; that's the whole point.
- A webcam that can sit **above** the keys looking straight down. A phone on a
  clamp, a desk-arm webcam, a tripod over the back of the keyboard. 720p is
  plenty. It needs to see the whole playing area with a bit of margin.
  If using a full sized keyboard - try just a small selected area an octave or two?
- Windows 10/11.
- On Windows, for the default **MPE** mode: **loopMIDI** (free) —
  https://www.tobias-erichsen.de/software/loopmidi.html. For **MIDI 2.0** mode
  instead: `winget install Microsoft.MIDI.SDK` and a loopback pair (see §3) —
  no loopMIDI needed for that path.
- A DAW with an MPE-capable synth (MPE mode), or software that speaks native
  MIDI 2.0 UMP (MIDI 2.0 mode).

Physical setup matters more than anything in software. The camera should look
**down** the keys, not across them at an angle, and the keyboard should fill
most of the frame. Even, diffuse light. Avoid a bright window behind the keys.
the camera should capture some of your arms also for the best results.

---

## 2. Install

Unzip anywhere. Everything's in the folder. Run `Sleight.exe`.
Windows SmartScreen may complain about an unknown publisher — "More info" →
"Run anyway".
AVG pops up does a scan and confirms it looks safe on the builds I have tested. 

## 3. The virtual MIDI port (MPE mode) — or a loopback pair (MIDI 2.0 mode)

**MPE mode (default):** Windows can't create a MIDI port that loops back into
itself, so a small free tool does it.

1. Install and run **loopMIDI**.
2. In the box at the bottom-left, type `Sleight`.
3. Click the **+** button. A port called `Sleight` appears in the list.
4. Leave loopMIDI running. It can live in the system tray.
5. On a fresh install, restart Windows once now. Until you do, your DAW (and
   Sleight) may not see the new port at all.

That's it — you only do this once. If you name the port something other than
`Sleight`, set `midi_out_match` in `config.json` to match.

**MIDI 2.0 mode instead:** no loopMIDI. Install Windows MIDI Services
(`winget install Microsoft.MIDI.SDK`), then create a loopback pair with two
clearly different names — full steps, including why the names need to
differ, are in QUICKSTART.md's MIDI 2.0 section.


## 4. Find your MIDI ports


You'll see your keyboard under inputs and `Sleight` (plus anything else) under
outputs. If Sleight later grabs the wrong keyboard, put a distinctive word from
its name into `config.json` → `midi_in_match`, e.g. `"MPK"` or `"KeyStep"`.
Leave it `""` to just take the first input.


## 5. Calibrate

With the webcam mounted:


One command, two steps:

**Step 1 — key range.** Sleight needs to know which MIDI note is your lowest
key and which is your highest, so it can line the video up with the keys. It
listens for 15 seconds — press your lowest key, then your highest. It saves
`lowest_note` / `highest_note` into `config.json` itself; nothing to copy by
hand. If no keyboard is connected it says so and skips the step, keeping
whatever's already in `config.json`. Common ranges, if you'd rather set them
directly instead — either hand-edit `config.json`, or use the Settings
window's **Camera & Calibration** tab, which has the same two numbers as
plain fields (click a field, then press that key on your keyboard, and it
fills itself in):
Advice: start with a single / two octave to test the features

| Keys | lowest_note | highest_note |
|---|---|---|
| 25 | 48 | 72 |
| 49 | 36 | 84 |
| 61 | 36 | 96 |
| 88 | 21 | 108 |

**Using less than your full keyboard on purpose:** the range doesn't have to
match your whole physical keyboard. Calibrating over a smaller span (say two
octaves in the middle) lets you mount the webcam closer to the keys for
sharper, more precise tracking, at the cost of only that span being
expressive. Set `lowest_note`/`highest_note` to the smaller range (by any of
the methods above) and click the camera corners around just that span in
Step 2 below.

**Step 2 — camera corners.** A window opens with the live camera view. Click
**four corners of the playing area, in this order**:

1. far edge, lowest key
2. far edge, highest key
3. near edge (toward you), highest key
4. near edge, lowest key

`u` undoes the last click. `Enter` saves. `Esc` (or just closing the window)
cancels and keeps whatever calibration you had before.

This builds a perspective transform from camera pixels to keyboard position, so
it doesn't matter that the camera's at an angle or slightly off-square. Redo the
whole thing any time the camera moves — there's an `r` hotkey for it while
running. Click the corners of the **key area**, not the whole keyboard body;
be reasonably precise, since a sloppy calibration shows up as the wrong note
bending.

Just want to re-check the key range without recalibrating the camera?
`Sleight.exe --midi-monitor` does that step on its own (reports only — it
doesn't save).

---

## 6. Set up the DAW

Generic steps — details vary by DAW:

1. In MIDI preferences, **enable `Sleight` as an input device**.
2. Create an **instrument track**, set its input to `Sleight`, arm it / enable
   input monitoring.
3. Load an **MPE-capable synth** and turn its MPE mode **on**.
4. Set the synth's MPE **pitch-bend range to 2 semitones** (match
   `per_note_pitch_bend_range` in `config.json`).

Synths that do MPE: Surge XT, Pigments, Vital, Equator/Equator2, MPE-mode
Massive X, Cypher2, most u-he synths, Kontakt with an MPE-aware instrument.

Notes per DAW:

- **REAPER** — enable `Sleight` under Preferences → MIDI Devices. On the track,
  set the input to it. For per-note bend you generally want the FX synth doing
  MPE rather than REAPER's own pitch handling.
- **Bitwig / Ableton Live 11+** — native MPE. Add the track, set input to
  `Sleight`, done. Live: turn on "MPE" in the track's MIDI-from section.
- **Logic** — enable `Sleight` in the MIDI environment, use an MPE-capable
  instrument, set the track to MPE.
- **Cubase** — "MIDI Remote" / note expression; enable the input and use a
  Note Expression-aware instrument.

You play your keyboard as normal; Sleight sits in the middle and adds the
expression. Your keyboard does **not** need to be plugged into the DAW
separately — Sleight passes the notes through.

---

## 7. Playing

Run `Sleight.exe`. Hold a note down and move that finger while it stays on the
key:

| Movement | Default output | Feel |
|---|---|---|
| slide **sideways** on the key | per-note pitch bend | a slow slide bends; a fast wiggle is vibrato |
| slide **forward / back** on the key | CC 74 | timbre / brightness sweep on that note |
| **curl or flatten** the finger | CC 1 (mod) | a third axis, whatever you map it to |

Because the finger never leaves the key, each movement belongs to exactly one
note. Hold a chord, wiggle one finger — only that note vibratos.

Everything is measured from where the finger was when the note started, so you
don't have to place your fingers precisely; you just move them from wherever
they landed.

Record the performance into a MIDI clip on the armed track like any other take.
It's ordinary MPE data afterwards — fully editable.

---

## 8. Remap what the movements do

`config.json` → `gesture_map`. One entry per axis (`glide` = sideways,
`slide` = forward/back, `curl` = finger curl):

```json
"gesture_map": {
  "glide": { "target": "pitchbend" },
  "slide": { "target": "cc", "cc": 74 },
  "curl":  { "target": "cc", "cc": 11 }
}
```

- `"target": "pitchbend"` — per-note pitch bend
- `"target": "cc", "cc": N` — control change N (0–127)
- `"target": "none"` — axis off

Then at the synth end, **MIDI-learn** each CC: right-click the parameter →
*MIDI Learn* → move that finger. In MPE mode the CC arrives on the note's own
member channel, so per-note learn works where the synth supports it.

Two common setups:

- *Seaboard-style:* glide→pitchbend, slide→CC74, curl→CC74 as well or curl→
  channel pressure via a CC your synth maps to "Press".
- *Sound-design:* glide→a filter cutoff CC, slide→resonance, curl→an FX send.

`invert_glide` / `invert_slide` / `invert_curl` flip a direction if it feels
backwards.

---

## 9. Every setting in config.json

**Output**

| key | meaning |
|---|---|
| `output_mode` | `"mpe"` (default) or `"midi2_ump"` — also a dropdown in the Settings window's MIDI tab now, no need to hand-edit this |
| `midi_out_match` | name of the loopMIDI port (`mpe`) or Windows MIDI Services endpoint (`midi2_ump`). Default `"Sleight"` |
| `midi_in_match` | substring of your keyboard's name. `""` = first input, or run `Sleight.exe --pick-midi-input` to identify it by playing a key |
| `midi2_bridge_exe` | `midi2_ump` only. `""` = the default bundled `midi2_bridge/publish/midi2_bridge.exe` |

**Keyboard & MPE**

| key | meaning |
|---|---|
| `lowest_note`, `highest_note` | MIDI note numbers of your end keys. Also settable directly in the Settings window's Camera tab - type them in, or click the field and press the key |
| `mpe_master_channel` | 1-based, lower zone. Default 1 |
| `mpe_member_channels` | how many notes can be expressive at once. Default 15 |
| `per_note_pitch_bend_range` | semitones. Match this in your synth. Default 2 |

**Camera & tracking**

| key | meaning |
|---|---|
| `camera_index` | 0 is usually the built-in / first webcam. Got more than one (laptop + external)? Run `Sleight.exe --pick-camera` instead of guessing numbers - it previews each one live, ENTER picks it and saves this for you |
| `camera_width`, `camera_height` | capture size. 960×540 is a good speed/quality point |
| `flip_horizontal` | mirror the view. Default true |
| `max_hands` | 1 or 2. Also a radio button in the Settings window's Camera tab - 1 is lighter on a weaker CPU if you only ever play with one hand |
| `min_detection_confidence`, `min_tracking_confidence` | MediaPipe thresholds. Lower = stickier but jitterier |
| `draw_hand_skeleton` | the luminous hand overlay in the cinematic view. Default true; turn off (a checkbox in Settings) to save draw time on a weaker machine - the keys, ribbons and finger dots stay either way |

**Expression feel**

| key | meaning |
|---|---|
| `glide_full_scale` | sideways travel for a full bend. Smaller = more sensitive. Default 0.06 |
| `slide_full_scale` | forward/back travel for full CC. Default 0.5 |
| `curl_full_scale` | curl amount for full CC. Default 0.35 |
| `glide_deadzone` | ignore sideways jitter smaller than this. Default 0.004 |
| `smoothing_ms` | low-pass on all three streams. Higher = smoother, laggier. Default 45 |
| `invert_glide` / `invert_slide` / `invert_curl` | flip a direction |

**MIDI 2.0 log**

| key | meaning |
|---|---|
| `write_ump_log` | write the UMP stream to a file. Default true |
| `ump_log_path` | where. Default `session.midi2.log` |

**vst_host mode — not in this build**

Doesn't ship in this build and isn't selectable from the Settings dropdown:
it needs the `pedalboard` library (GPLv3-licensed — bundling it into this
compiled .exe would be a real licensing problem, not just a technicality)
plus `sounddevice`. Stick to `mpe` or `midi2_ump`.

---

## 10. On-screen views and hotkeys

While running:

| key | does |
|---|---|
| `q` / `Esc` | quit |
| `v` | cycle the view (stage / ghost-with-camera) |
| `r` | re-run calibration |
| `s` | open the **full settings window** — MIDI, camera, hands, key range, gestures, everything (same key whether or not Caps Lock is on) |
| `u` | open the **MIDI 2.0 UMP viewer** |
| `p` `P` `e` | next patch / previous patch / show editor — only do anything in vst_host mode, not available in this build (see §9) |

`s` opens the same full settings window as `--settings` — MIDI ports, camera
index/resolution, hand count, key range, the hand-skeleton toggle, and
gestures (on/off, pitch-bend-or-CC, CC number, invert, sensitivity for each
of glide/slide/curl). Changing camera/hand/key-range settings needs that
subsystem rebuilt to actually take effect, so click **Save & Run** and
Sleight cleanly restarts the session (camera and tracking reopen with
whatever you changed) without you ever having to quit and relaunch by hand.

`--view plain` swaps the visualiser for a flat debug overlay: fingertip dots, a line
from each finger to the key it's bound to, and three bars per note
(orange = glide, blue = slide, purple = curl). Use it when something's not
tracking right.

---

## 11. The MIDI 2.0 log, and the UMP viewer

Sleight builds real MIDI 2.0 Universal MIDI Packet messages for everything it
does — 32-bit per-note pitch bend, registered per-note controllers, poly
pressure — and writes them to `session.midi2.log` next to the exe, always,
regardless of output mode.

Most DAWs still only take MPE (MIDI 1.0) over a port, which is why that's the
default. But `output_mode = "midi2_ump"` sends this same data live over a real
Windows MIDI Services endpoint, for software that specifically speaks UMP —
see the MIDI 2.0 setup steps in QUICKSTART.md for how to wire that up. The log
described below is always available either way, as a plain-text record of the
same data: each line has the raw UMP hex words alongside a plain-English
description.

Rather than open the file in a text editor, press **`u`** (or run
`Sleight.exe --ump-viewer` on its own, without a camera or MIDI session, to
watch a log from a previous run) for a live, colour-coded, scrolling view of
it — green for note-on, brown for note-off, and orange/blue/purple for
per-note bend/slide/curl matching the same colours used everywhere else in
the app. By default it only shows note-on/note-off, since the continuous
per-note updates are 3 lines per held note *per frame* and drown everything
else out; tick **"show continuous bend/slide/curl"** when you actually want
to see that firehose (good for demoing the real-time UMP resolution — it's
the clearest way to show what "MIDI 2.0 native" actually means for this
project). There's also a text filter box, e.g. type `curl` to see only curl
activity. It tails the file - it doesn't touch the running engine, so it
costs nothing extra to leave open, live or in a separate viewer instance.

---

## 12. When it doesn't work

**"No MIDI-out port named 'Sleight'"** — loopMIDI isn't running, or the port
isn't named `Sleight`. Open loopMIDI, check the port list. `--list-ports` shows
what Sleight can see.

**Nothing reaches the DAW** — the `Sleight` input device isn't enabled in the
DAW, or the track isn't armed / monitoring. Check the synth is actually in MPE
mode.

**Notes play but no bend/timbre** — synth isn't in MPE mode, or its bend range
doesn't match `per_note_pitch_bend_range`. Some synths need MPE switched on
per-patch.

**The expression lags my fingers, or the perf line shows a low fps** — check
which part is slow first: the console prints `track Xms draw Yms loop Zms`
every couple of seconds. `track` is mediapipe (hand tracking); `draw` is the
cinematic visualiser, which composites at a fixed internal resolution
regardless of your camera settings, so lowering `camera_width`/`camera_height`
mainly helps `track`, not `draw`. On an older/weaker CPU `draw` is usually the
big one - run with **`--view none`** to skip it entirely (tracking and MIDI
still run exactly the same, you just don't see the picture) or **`--view plain`**
for a much cheaper debug overlay instead of the full visualiser. Lowering
`smoothing_ms` a little and making sure nothing else is hammering the CPU
helps either way.

**Fingertips jitter when still** — more/even light, raise
`min_tracking_confidence` a touch, or raise `smoothing_ms`. A small
`glide_deadzone` also helps for the pitch axis.

**The wrong note bends** — calibration is off. Redo it (`r`), clicking the
corners of the key area carefully. Check `lowest_note`/`highest_note` are right.

**Expression jumps to another note when fingers get close** — two fingertips
crossed and the tracker swapped their ids. It settles on its own within a
frame or two. Playing with a bit more finger separation helps; this is the
main limitation of single-camera tracking.

**A note has no expression at all** — no finger was near the key when it
sounded (fast run, or the hand was occluded). The note still plays; it just
stays flat. Rare in practice.

