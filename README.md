# Sleight — per-note expression for any keyboard

Turn an ordinary MIDI keyboard into a per-note expressive controller with a
plain webcam. You play normally; a camera above the keys watches the finger
still holding each note and turns its small movements into independent
expression on that one note:

| Finger movement, while the key stays down | Default output |
|---|---|
| slide **sideways** on the key | per-note pitch bend |
| ...as a fast wiggle | per-note vibrato — its own speed and depth on every held note |
| slide **forward / back** on the key | CC 74 |
| **curl / flatten** the finger | CC 1 |

Each axis remaps (`gesture_map` in `config.json`) to a per-note bend or any CC,
which you MIDI-learn at the synth. Because the finger never leaves the key, the
movement belongs to exactly one note — so two notes of a chord can vibrato
independently, which a normal keyboard physically can't do.

By default it outputs **MPE** on a virtual MIDI port, so in a DAW it looks
like any other controller — most DAWs and synths only take MPE, which is why
that's the default. Sleight also builds the real **MIDI 2.0 UMP** messages for
everything — 32-bit per-note pitch bend, registered per-note controllers, poly
pressure — and can send them live over a real Windows MIDI Services endpoint
(`output_mode = "midi2_ump"`) for software that specifically speaks UMP; see
MANUAL.md.

**Prior art, honestly:** ROLI's Airwave (2025) does camera-tracked per-note
expression, but with infrared hardware and free-air gestures above the keys.
Webcam projects like Handmate and MadHand map a hand to one CC and aren't tied
to the keys at all. Sleight's niche is a standard webcam, fingers on the keys,
each gesture bound to the note it belongs to.

---

## See it

[![Sleight demo](https://img.youtube.com/vi/vwOdRIJnrD8/hqdefault.jpg)](https://youtu.be/vwOdRIJnrD8)

Watch the demo: [youtu.be/vwOdRIJnrD8](https://youtu.be/vwOdRIJnrD8) - sideways bend, forward/back slide and curl, per note, on an ordinary MIDI keyboard.

Set it up in about 5 minutes: [setup guide (loopMIDI + Reaper)](https://youtu.be/FGAhWjG5eXo).

---

## Get it

**Windows build (no Python needed):** download the latest zip from the
[Releases page](../../releases), unzip anywhere and run `Sleight.exe`.
Windows 10/11, any class-compliant MIDI keyboard, a webcam mounted above the keys.

**From source:** Python 3.12, then

```
pip install -r requirements.txt
python main.py
```

`python build.py` produces the same standalone folder as the release zip
(needs PyInstaller; the two MIDI 2.0 bridges below must be published first).

## Run it

Needs a virtual MIDI port: install
[loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) and add one
named `Sleight`. Then in your DAW: enable
`Sleight` as an input, make an instrument track from it, load an MPE synth
(MPE on, bend range 2), arm it.

Full walkthrough and every setting: **`MANUAL.md`**. Five-minute version:
**`QUICKSTART.md`**.

### While running
`q` quit · `v` cycle view · `r` re-calibrate · `s` settings · `u` MIDI 2.0 UMP
viewer · `p` / `Shift+P` next / previous patch · `e` show synth editor ·
`--view plain` for the debug overlay

### MIDI 2.0 bridges (optional)

`output_mode = "midi2_ump"` sends through a small .NET companion exe. Two are
included, because Windows MIDI Services ships in two forms; Sleight tries both:

- `midi2_bridge/` - the separate App SDK (`winget install Microsoft.MIDI.SDK`)
- `midi2_bridge_inbox/` - the in-box preview (Windows 11 25H2, inbox-dev-preview-9).
  Download `Windows.Devices.Midi2.0.99.83-devpreview.9.nupkg` from
  [microsoft/MIDI releases](https://github.com/microsoft/MIDI/releases/tag/inbox-dev-preview-9)
  into `midi2_bridge_inbox/vendor/` first (it isn't on nuget.org).

Build either with `dotnet publish -c Release -r win-x64 --self-contained false -p:Platform=x64 -o publish`
from inside its folder.

---

## Requirements

Python 3.12. `mediapipe` (Apache-2.0), `opencv-python` (Apache-2.0),
`python-rtmidi` (MIT), `python-osc` (public domain), `numpy` (BSD). The
`vst_host` mode additionally needs `pedalboard` (**GPLv3**) + `sounddevice`
(MIT) - not installed by default and deliberately kept out of the distributed
build (`build.py`), so the release binary stays MIT-clean.

## Support

Sleight is free. A MIDI Innovation Awards 2026 finalist (Software Prototypes /
Non-Commercial). Made by Dean Coyle - [youtube.com/@deancoyle](https://www.youtube.com/@deancoyle).

## License

MIT — see [LICENSE](LICENSE). Third-party components and their licences are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
