// midi2_bridge_inbox - same stdin/stdout line protocol as ../midi2_bridge, but built against the
// in-box Windows MIDI Services API (NuGet "Windows.Devices.Midi2" 0.99.x-devpreview, namespace
// Windows.Devices.Midi2) instead of the separately-installed App SDK runtime
// (Microsoft.Windows.Devices.Midi2, MidiDesktopAppSdkInitializer). Windows MIDI Services lives in
// System32 on in-box builds, so there is no SDK runtime to initialise - just MidiApi.
//
//   SEND <hex> <hex>   -> "OK" | "FAIL <reason>"
//   PING               -> "PONG <connected-endpoint-name>"
//   QUIT               -> exits
//   --port <substring> picks the endpoint (first whose name contains it), --listen echoes RECV lines.
//
// Any startup problem prints one line starting "STARTFAIL" and exits 1 - on a machine that
// doesn't have the in-box API at all, that is "STARTFAIL api-not-available:..." and Sleight
// falls back to the other bridge.

using System;
using System.Linq;
using Windows.Devices.Midi2;
using Windows.Devices.Midi2.Enumeration;

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
    try
    {
        if (!MidiApi.EnsureServiceAvailable())
        {
            Console.WriteLine("STARTFAIL service-unavailable");
            return 1;
        }
    }
    catch (Exception ex)
    {
        Console.WriteLine($"STARTFAIL api-not-available:{ex.GetType().Name}:{ex.Message}");
        return 1;
    }

    MidiSession session = MidiSession.Create("Sleight (Expressive MIDI 2.0 Keyboard)");

    var endpoints = MidiEndpointDeviceInformation.FindAll(
        MidiEndpointDeviceInformationSortOrder.Name,
        MidiEndpointDeviceInformationFilters.AllStandardEndpoints);
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
    return 0;
}
