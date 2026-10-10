"""
Build the standalone Windows folder.

    python build.py

Output: dist/Sleight/ - Sleight.exe plus the assets it loads at runtime
(the hand model, a fresh config.json, the docs, and midi2_bridge/publish/
for output_mode = "midi2_ump"). No synth is bundled; by default MIDI goes
out a loopMIDI port to the user's DAW. Zip the folder and send it.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist" / "Sleight"

# copied next to the .exe. config.py finds them via sys.executable when frozen.
ASSETS = ["hand_landmarker.task", "icon.ico", "icon.png",
          "QUICKSTART.md", "MANUAL.md", "README.md", "LICENSE", "THIRD_PARTY.md"]


def run(cmd):
    print(">", " ".join(cmd))
    subprocess.check_call(cmd)


def main():
    for d in (HERE / "build", HERE / "dist"):
        shutil.rmtree(d, ignore_errors=True)

    # --console so the setup commands (--list-ports, --midi-monitor) have
    # somewhere to print. engine.py / hud.py get picked up as imports.
    #
    # --collect-all mediapipe grabs its whole package tree. mediapipe's own
    # __init__ imports matplotlib unconditionally (tried excluding it -
    # "mediapipe import failed: No module named 'matplotlib'" - so that one
    # has to stay). scipy isn't in that chain and our code never touches it,
    # so just that one's excluded.
    #
    # pedalboard + sounddevice are excluded on purpose: they're only for the
    # optional output_mode="vst_host" path (vst_output.py), which nothing in
    # this build's shipped config.json uses, and pedalboard is GPLv3 - fine
    # to have installed for local dev, but this project's source isn't public,
    # so a compiled .exe with GPLv3 native code baked in and no corresponding
    # source available would be a real licensing problem, not a technicality.
    # If pedalboard happens to be installed in the environment building this,
    # PyInstaller's static analysis would otherwise sweep it in regardless of
    # whether vst_host mode is ever actually used - excluding it here means
    # this build genuinely doesn't contain it. (vst_host mode still works
    # fine running from source with `pip install pedalboard sounddevice`;
    # it just fails cleanly with a clear message in a build like this one.)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--name", "Sleight",
         "--console", "--icon", str(HERE / "icon.ico"),
         "--collect-all", "mediapipe",
         "--exclude-module", "scipy",
         "--exclude-module", "pedalboard",
         "--exclude-module", "sounddevice",
         str(HERE / "main.py")])

    for name in ASSETS:
        src = HERE / name
        if src.exists():
            shutil.copy2(src, DIST / name)

    # Windows ships its own Universal CRT (ucrtbase.dll) in every install
    # since Win10 - that's the whole point of the UCRT being a system
    # component rather than an app-bundled redistributable. PyInstaller's
    # dependency scan grabs a copy anyway from the build machine, so the
    # frozen app ends up with two ucrtbase.dll instances able to load in
    # the same process (system one + this bundled one). A real crash here
    # (Sleight.exe, 26/09/2026) faulted inside ucrtbase.dll with both
    # copies loaded - a known class of frozen-Python-app crash. Deleting
    # the bundled copy forces the loader to use only the system one;
    # everything else in _internal still finds it via the normal DLL
    # search path, same as any other exe on Windows.
    bundled_ucrtbase = DIST / "_internal" / "ucrtbase.dll"
    if bundled_ucrtbase.exists():
        bundled_ucrtbase.unlink()
        print("  removed bundled _internal/ucrtbase.dll (using system copy only)")

    # output_mode = "midi2_ump" (midi2_output.py) shells out to this
    # companion .NET exe rather than importing anything - PyInstaller's
    # static analysis has no way to know that dependency exists, so the
    # published build output has to be copied in by hand here. It's the
    # bridge's *published* output (midi2_bridge/publish/, built with
    # `dotnet publish -c Release -r win-x64 --self-contained false -o
    # publish` from inside midi2_bridge/) - not the source or bin/obj -
    # and midi2_output.py._default_bridge_exe() expects it at exactly
    # midi2_bridge/publish/ next to the frozen exe, matching this layout.
    bridge_publish = HERE / "midi2_bridge" / "publish"
    if bridge_publish.exists():
        shutil.copytree(bridge_publish, DIST / "midi2_bridge" / "publish",
                         dirs_exist_ok=True)
        print(f"  bundled midi2_bridge (output_mode = \"midi2_ump\") from {bridge_publish}")
    else:
        print(f"  ! {bridge_publish} not found - output_mode \"midi2_ump\" won't work in "
              f"this build. Run: cd midi2_bridge && dotnet publish -c Release -r win-x64 "
              f"--self-contained false -o publish   then rebuild.")

    # Second bridge, built against the in-box Windows MIDI Services API (preview 9
    # onward) - midi2_output.py tries the App SDK bridge above first and falls back
    # to this one, so MIDI 2.0 mode works on either kind of machine.
    # Built with: cd midi2_bridge_inbox && dotnet publish -c Release -r win-x64
    #   --self-contained false -p:Platform=x64 -o publish
    inbox_publish = HERE / "midi2_bridge_inbox" / "publish"
    if inbox_publish.exists():
        shutil.copytree(inbox_publish, DIST / "midi2_bridge_inbox" / "publish",
                         dirs_exist_ok=True)
        print(f"  bundled midi2_bridge_inbox (in-box API) from {inbox_publish}")
    else:
        print(f"  ! {inbox_publish} not found - MIDI 2.0 mode won't work on machines with "
              f"only the in-box preview. Build it first (see comment above), then rebuild.")

    # ship a clean config, not whatever's on this machine
    shutil.copy2(HERE / "config.example.json", DIST / "config.json")

    print("\nBuilt:", DIST)
    print("Zip it and send. First run: unzip, run Sleight.exe, then make a")
    print("loopMIDI port named 'Sleight' (QUICKSTART.md has the steps).")


if __name__ == "__main__":
    main()
