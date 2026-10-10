# Sleight — quick start

Per-note pitch bend, vibrato, timbre and finger-curl on **any** MIDI keyboard,
using a webcam. You play normally; a camera above the keys watches the finger
holding each note and shapes that note on its own.

Sleight sends the expression out as **MPE** on a virtual MIDI port. It shows up
in your DAW as a MIDI **input** — like a Seaboard or a LinnStrument would.
Nothing plays sound on its own; you pick the synth in your DAW.

Most of the setup below (ports, camera, calibration, hand count, key range,
what each finger axis does) can also be done from one window instead of
flags and JSON: `Sleight.exe --settings`, or just press **`s`** any time
Sleight is already running (Caps Lock doesn't matter - same key either way).

## You need

- A MIDI keyboard (anything class-compliant — no driver on Windows)
- A webcam you can mount **above** the keyboard, looking straight down
- Windows 10/11
- **loopMIDI** — free, one-time install: https://www.tobias-erichsen.de/software/loopmidi.html

## One-time setup

### 1. Make the virtual MIDI port

Install and open **loopMIDI**. In the box at the bottom left, type **`Sleight`**
and click the **+** button. You now have a port called `Sleight`. Leave loopMIDI
running (it can sit in the tray). **On a fresh install, restart Windows once
after creating the port** — until you do, your DAW (and Sleight) may not see
it at all.

### 2. First run of Sleight

Unzip anywhere, double-click **`Sleight.exe`**. A console window opens.
*(SmartScreen may warn — "More info" → "Run anyway".)*

- It prints your MIDI ports on startup. If it grabs the wrong keyboard, close it,
  open `config.json` in Notepad and set `"midi_in_match"` to part of your
  keyboard's name (e.g. `"MPK"`).
- If it says it can't find the `Sleight` port, go back to step 1.
- No calibration yet? It notices and walks you straight into it (see step 3
  below) rather than just quitting - so it's fine to double-click it cold.

### 3. Calibrate

Mount the webcam above the keys, then run `Sleight.exe --calibrate`. Two steps,
one command:

1. **Key range** — it listens for 15s; play your lowest key, then your highest.
   Saved straight into `config.json` as `lowest_note` / `highest_note` — nothing
   to copy by hand.
2. **Camera corners** — click the four corners of the key area (far-left,
   far-right, near-right, near-left), then press Enter.

Re-run it any time the camera moves. `Sleight.exe --midi-monitor` re-checks just
the key range on its own, without touching the camera calibration.

### 4. Set up the DAW track

- In your DAW's MIDI settings, enable **`Sleight`** as an input device.
- New instrument track → input = `Sleight` → arm it.
- Load an MPE-capable synth (Surge XT, Pigments, Vital, Equator, MPE-mode
  Massive X, etc.) and turn its **MPE** mode on.
- Bend range: set the synth's MPE pitch-bend range to **2 semitones**
  (matches `per_note_pitch_bend_range` in `config.json`).

## Play

Run `Sleight.exe`. Hold a note and move the finger that's holding it:

| Movement | Sends (default) |
|---|---|
| slide **sideways** on the key | per-note pitch bend |
| **wiggle** sideways | per-note vibrato (it's just fast pitch bend) |
| slide **forward / back** on the key | CC 74 |
| **curl / flatten** the finger on the key | CC 1 (mod) |

Every note of a chord is shaped independently. Record the performance into a
MIDI clip on the track like any other take — it stays fully editable.

## Choose what each movement does

Open `config.json` → `gesture_map`. Each axis (`glide` = sideways, `slide` =
forward/back, `curl`) takes:

- `{ "target": "pitchbend" }` — per-note pitch bend
- `{ "target": "cc", "cc": 74 }` — any CC number 0–127
- `{ "target": "none" }` — off

Then, at the synth or DAW end, **MIDI-learn** each CC to the parameter you want:
right-click a knob → *MIDI Learn* → move that finger. In MPE mode the CC arrives
on the note's member channel, so per-note learn works too.

`invert_glide` (sideways) / `invert_slide` (forward-back) / `invert_curl` flip a
direction. `curl_full_scale` (default 0.35) sets how much curl = full output —
smaller is more sensitive.

## Keys while running

`q` quit · `v` cycle view · `r` re-calibrate · `s` settings (MIDI, camera,
hands, key range, gestures - restarts) · `u` MIDI 2.0 UMP viewer ·
`e` show synth editor · `p` / `Shift+P` next / previous patch

## Nothing reaching the DAW?

- loopMIDI open, with a port named exactly `Sleight`? (`Sleight.exe --list-ports`)
- DAW input device `Sleight` enabled, track armed, monitoring on?
- Synth actually in MPE mode?

## MIDI 2.0

Sleight computes true MIDI 2.0 UMP per-note messages, and — as of this build —
can send them live over a real Windows MIDI Services endpoint, not just log
them. Most people should stick with MPE (the default): it needs no extra
install and every DAW/synth already understands it. MIDI 2.0 mode is for
software that specifically speaks UMP.

**One-time setup:**

1. Install Windows MIDI Services: `winget install Microsoft.MIDI.SDK`
   (this also gives you the `midi` console tool used below). On Windows 11
   25H2+ you can instead use Microsoft's in-box preview from
   github.com/microsoft/MIDI/releases (Tools + a loopback transport) —
   Sleight detects which one you have and uses the matching bridge.
2. Create a loopback pair with **two clearly different names** — this
   matters: `midi_out_match` picks the first port whose name *contains*
   what you typed, so if both sides share a word ("Sleight In" / "Sleight
   Out") it can match either one unpredictably. Use e.g.:
   `midi loopback create --name-a "Sleight" --name-b "SleightReceiver"`
3. In `config.json`: set `"output_mode": "midi2_ump"` and
   `"midi_out_match": "Sleight"` (matches side A — where Sleight sends).
4. In your DAW/synth, pick **"SleightReceiver"** (side B) as the MIDI
   input — not "Sleight" itself. Whatever's sent into side A arrives as
   input on side B, same two-ends-of-a-cable idea as a real MIDI cable.
5. Press `u` while Sleight is running to confirm live UMP is actually
   flowing (decoded, colour-coded, in real time).
