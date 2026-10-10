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
    property string subscriptionId: ""
    property bool canSelect: false
    property string errorText: ""
    property string pendingServerId: ""
    property string pendingSubscriptionId: ""
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
                    root.subscriptionId = result.subscriptionId || "";
                    root.canSelect = !!result.canSelect;
                    if (root.controlBusy && (root.pendingServerId ? root.serverId === root.pendingServerId && root.subscriptionId === root.pendingSubscriptionId && root.connected : root.connected === root.requestedState)) {
                        root.pendingServerId = "";
                        root.errorText = "";
                        root.controlBusy = false;
                        controlTimeout.stop();
                    }
                } catch (error) { root.connected = false; }
            }
        }
    }
    Timer { interval: 2000; running: true; repeat: true; onTriggered: if (!probe.running) probe.running = true }
    function openHapp() { Quickshell.execDetached(["python3", Caching.serpantinumDir + "/scripts/vpn-control.py", "open"]); }
    Process {
        id: control
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text);
                    if (!result.ok) {
                        root.errorText = result.error || "Happ отклонил команду";
                        root.controlBusy = false;
                        root.pendingServerId = "";
                        controlTimeout.stop();
                    }
                } catch (error) {
                    root.errorText = "Нет ответа от Happ";
                    root.controlBusy = false;
                    controlTimeout.stop();
                }
            }
        }
    }
    Timer { id: controlTimeout; interval: 15000; onTriggered: { root.controlBusy = false; root.pendingServerId = ""; root.errorText = "Happ не подтвердил изменение подключения"; } }
    function selectServer(subscription, server) {
        if (controlBusy || control.running) return;
        if (subscription === subscriptionId && server === serverId) return;
        if (!canSelect) { errorText = "Выбор серверов доступен после следующего запуска Happ с адаптером"; return; }
        errorText = "";
        pendingServerId = server;
        pendingSubscriptionId = subscription;
        controlBusy = true;
        control.command = ["python3", Caching.serpantinumDir + "/scripts/vpn-control.py", "select", subscription, server];
        control.running = true;
        controlTimeout.restart();
    }
    function toggle() {
        if (controlBusy || control.running) return;
        errorText = "";
        pendingServerId = "";
        requestedState = !connected;
        controlBusy = true;
        control.command = ["python3", Caching.serpantinumDir + "/scripts/vpn-control.py", requestedState ? "connect" : "disconnect"];
        control.running = true;
        controlTimeout.restart();
    }
}
