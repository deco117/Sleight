// midi2_bridge - a tiny stdin/stdout pipe onto a real Windows MIDI Services
// (Microsoft.Windows.Devices.Midi2 "App SDK") UMP endpoint connection.
//
// Why this exists: Windows MIDI Services' app-facing client API is only
// distributed as a WinRT component for C++/WinRT and C#/WinRT
// (Microsoft.Windows.Devices.Midi2 nupkg, GitHub-only - see
// https://github.com/microsoft/MIDI/releases). There is no PyPI package:
// winsdk (the pywinrt-generated Windows SDK projection) only covers the base
// Windows SDK, which does not include this namespace, and no prebuilt
// pywinrt projection for it exists anywhere in the microsoft/MIDI repo or on
// PyPI (checked directly - no bindings/python folder, no .whl, no
// winrt-Windows.Devices.Midi2 package). Generating one from scratch would
// mean running PyWinRT's native C++ code generator against the winmd - a much
// heavier, still native-toolchain-bound job. Instead, this small
// self-contained .NET console app talks the real WinRT API directly - the
// same App SDK bootstrap + send sequence Microsoft's own csharp-net sample
// uses (samples/csharp-net/message-light-wpf, which references the same
// Microsoft.Windows.Devices.Midi2 package) - and exposes it to Sleight's
// Python process over a dead-simple line protocol on stdin/stdout.
//
// Sleight's Python side (midi2_output.py) keeps owning all UMP *message
// construction* (it reuses ump.py's word builders exactly as it does for the
// logger) - this process only opens the endpoint connection and forwards the
// already-built 32-bit word pairs. No WinRT/winsdk import ever happens in
// Python; this process is the only thing that touches the Midi2 API, and it
// is only launched when output_mode == "midi2_ump" is selected.
//
// Protocol (one command per line on stdin, one reply line on stdout):
//   SEND <word0hex> <word1hex>   -> "OK" or "FAIL <reason>"
//   PING                          -> "PONG <connected-endpoint-name>"
//   QUIT                          -> disconnects, closes session, exit 0
//
// --listen also prints one "RECV <word0hex> <word1hex>" line per incoming
// UMP message as it arrives (used only for standalone loopback verification -
// Sleight itself never needs this, it only sends).
//
// Anything wrong on startup (SDK runtime not installed, service unavailable,
// no matching endpoint, failed to open) is printed as a single line starting
// "STARTFAIL " and the process exits 1 - Python treats that as "this backend
// did not come up" and reports it, rather than silently doing nothing.

using System;
using System.Linq;
using Microsoft.Windows.Devices.Midi2;
using Microsoft.Windows.Devices.Midi2.Initialization;
using Microsoft.Windows.Devices.Midi2.Messages;

string portMatch = "";
bool listen = false;
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "--port" && i + 1 < args.Length)
    {
        portMatch = args[i + 1];
    }
    else if (args[i] == "--listen")
    {
        listen = true;
    }
}

return Run(portMatch, listen);

static int Run(string portMatch, bool listen)
{
    MidiDesktopAppSdkInitializer? initializer;
    try
    {
        initializer = MidiDesktopAppSdkInitializer.Create();
    }
    catch (Exception ex)
    {
        Console.WriteLine($"STARTFAIL sdk-not-installed:{ex.Message}");
        return 1;
    }

    if (initializer == null)
    {
        Console.WriteLine("STARTFAIL sdk-not-installed");
        return 1;
    }

    if (!initializer.InitializeSdkRuntime())
    {
        Console.WriteLine("STARTFAIL runtime-init-failed");
        return 1;
    }

    if (!initializer.EnsureServiceAvailable())
    {
        Console.WriteLine("STARTFAIL service-unavailable");
        return 1;
    }

    MidiSession session = MidiSession.Create("Sleight (Expressive MIDI 2.0 Keyboard)");

    var endpoints = MidiEndpointDeviceInformation.FindAll();
    if (endpoints.Count == 0)
    {
        Console.WriteLine("STARTFAIL no-endpoints-found");
        session.Dispose();
        return 1;
    }

    MidiEndpointDeviceInformation? chosen = null;
    if (!string.IsNullOrEmpty(portMatch))
    {
        chosen = endpoints.FirstOrDefault(
            e => e.Name.Contains(portMatch, StringComparison.OrdinalIgnoreCase));
    }
    chosen ??= endpoints[0];

    MidiEndpointConnection connection = session.CreateEndpointConnection(chosen.EndpointDeviceId);
    if (!connection.Open())
    {
        string names = string.Join(" | ", endpoints.Select(e => e.Name));
        Console.WriteLine($"STARTFAIL open-failed endpoint='{chosen.Name}' seen=[{names}]");
        session.Dispose();
        return 1;
    }

    string endpointName = chosen.Name;

    if (listen)
    {
        connection.MessageReceived += (sender, e) =>
        {
            IMidiUniversalPacket packet = e.GetMessagePacket();
            if (packet is MidiMessage64 m64)
            {
                Console.WriteLine($"RECV {m64.Word0:X8} {m64.Word1:X8}");
            }
            else
            {
                Console.WriteLine($"RECV other packetType={packet.PacketType}");
            }
        };
    }

    // Ready. Everything from here on is driven by stdin lines.
    string? line;
    while ((line = Console.ReadLine()) != null)
    {
        line = line.Trim();
        if (line.Length == 0) continue;

        string[] parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string cmd = parts[0].ToUpperInvariant();

        if (cmd == "QUIT")
        {
            break;
        }
        else if (cmd == "PING")
        {
            Console.WriteLine($"PONG {endpointName}");
        }
        else if (cmd == "SEND" && parts.Length >= 3)
        {
            try
            {
                uint word0 = Convert.ToUInt32(parts[1], 16);
                uint word1 = Convert.ToUInt32(parts[2], 16);
                MidiSendMessageResults result = connection.SendSingleMessageWords(0, word0, word1);
                if (MidiEndpointConnection.SendMessageSucceeded(result))
                {
                    Console.WriteLine("OK");
                }
                else
                {
                    Console.WriteLine($"FAIL {result}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"FAIL exception:{ex.Message}");
            }
        }
        else
        {
            Console.WriteLine($"FAIL unknown-command:{line}");
        }
    }

    session.DisconnectEndpointConnection(connection.ConnectionId);
    session.Dispose();
    initializer.ShutdownSdkRuntime();
    initializer.Dispose();
    return 0;
}
