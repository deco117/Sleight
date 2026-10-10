# Third-party components

Sleight itself is MIT licensed (see LICENSE). It uses, and in the Windows
release zip ships, the following third-party components under their own licences.

| Component | Used for | Licence |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) (`mediapipe` package) and its `hand_landmarker.task` hand-tracking model | Finding hands and fingertips in the camera image | Apache-2.0 |
| [OpenCV](https://opencv.org/) (`opencv-python`) | Camera capture, drawing, calibration maths | Apache-2.0 |
| [NumPy](https://numpy.org/) | Numerics | BSD-3-Clause |
| [python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) | MIDI in/out | MIT |
| [python-osc](https://github.com/attwad/python-osc) | Optional OSC output mode | Unlicense / public domain |
| Windows MIDI Services (`Microsoft.Windows.Devices.Midi2.NetProjection.dll` in `midi2_bridge/vendor`, and the `Windows.Devices.Midi2` package for the in-box bridge) | MIDI 2.0 UMP output | MIT (Microsoft) |
| [PyInstaller](https://pyinstaller.org/) | Packaging the Windows build only | GPL-2.0 with the bootloader exception (output may be distributed under any licence) |

Not included, and not required: loopMIDI (Tobias Erichsen, free for personal
use - install it yourself) and Surge XT (GPLv3, only for users who choose it as
their own synth). `pedalboard` (GPLv3) is only used if you opt in to
`output_mode = "vst_host"` from source, and is kept out of the release build.

If you redistribute the Windows release zip, keep this file with it.
