pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "../"

Item {
    id: root
    property bool connected: false
    property string location: "Happ"
    property string serverId: ""
    property bool controlBusy: false
    property bool requestedState: false
    Process {
        id: probe
        running: true
        command: ["python3", Caching.serpantinumDir + "/scripts/vpn-status.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    root.connected = result.connected;
                    root.location = result.location;
                    root.serverId = result.serverId || "";
                    if (root.controlBusy && root.connected === root.requestedState) {
                        root.controlBusy = false;
                        controlTimeout.stop();
                    }
                } catch (error) { root.connected = false; }
            }
        }
    }
    Timer { interval: 2000; running: true; repeat: true; onTriggered: if (!probe.running) probe.running = true }
    function openHapp() { Quickshell.execDetached(["python3", Caching.serpantinumDir + "/scripts/vpn-control.py", "open"]); }
    Process { id: control }
    Timer { id: controlTimeout; interval: 15000; onTriggered: root.controlBusy = false }
    function toggle() {
        if (controlBusy || control.running) return;
        requestedState = !connected;
        controlBusy = true;
        control.command = ["python3", Caching.serpantinumDir + "/scripts/vpn-control.py", requestedState ? "connect" : "disconnect"];
        control.running = true;
        controlTimeout.restart();
    }
}
