import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "../"
import "../vpn"

Rectangle {
    id: root
    color: ThemeBackend.base
    radius: ThemeBackend.borderRadius
    property real uiScale: 1
    function s(value) { return Math.round(value * uiScale); }
    property var servers: []
    property string errorText: ""
    property int updated: 0
    property bool fastestFirst: false
    readonly property var filtered: {
        const query = search.text.toLowerCase().trim();
        let rows = servers.filter(row => (row.name + " " + row.subscription).toLowerCase().includes(query));
        if (fastestFirst) rows.sort((a, b) => (a.ping || 999999) - (b.ping || 999999));
        return rows;
    }
    function refresh(ping) {
        if (reader.running) return;
        reader.command = ["python3", Caching.serpantinumDir + "/scripts/vpn-locations.py"];
        if (ping) reader.command = reader.command.concat(["--ping"]);
        reader.running = true;
    }
    onVisibleChanged: if (visible) refresh(false)
    Component.onCompleted: if (visible) refresh(false)
    Timer { interval: 30000; running: root.visible; repeat: true; onTriggered: root.refresh(false) }
    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(text);
                    root.servers = data.locations || [];
                    root.updated = data.updated || 0;
                    root.errorText = data.error || "";
                } catch (error) { root.errorText = "Не удалось получить локации Happ"; }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.s(22)
        spacing: root.s(12)
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: root.s(4)
                Text { text: "Локации"; color: ThemeBackend.text; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(23); font.bold: true }
                Text { text: root.servers.length + " серверов · из Happ"; color: ThemeBackend.subtext0; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(12) }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: root.s(160); implicitHeight: root.s(38)
                radius: height / 2; color: reader.running ? ThemeBackend.surface0 : ThemeBackend.blue
                Text { anchors.centerIn: parent; text: reader.running ? "Проверяем…" : "↻ Проверить пинг"; color: reader.running ? ThemeBackend.subtext0 : ThemeBackend.base; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(12); font.bold: true }
                MouseArea { anchors.fill: parent; enabled: !reader.running; cursorShape: Qt.PointingHandCursor; onClicked: root.refresh(true) }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: root.s(8)
            TextField {
                id: search
                Layout.fillWidth: true
                implicitHeight: root.s(40)
                placeholderText: "Найти страну или сервер…"
                color: ThemeBackend.text
                placeholderTextColor: ThemeBackend.subtext0
                font.family: ThemeBackend.fontFamily
                font.pixelSize: root.s(13)
                leftPadding: root.s(14)
                background: Rectangle { color: ThemeBackend.surface0; radius: ThemeBackend.borderRadius }
            }
            Rectangle {
                implicitWidth: root.s(135); implicitHeight: root.s(40)
                radius: ThemeBackend.borderRadius
                color: root.fastestFirst ? ThemeBackend.blue : ThemeBackend.surface0
                Text { anchors.centerIn: parent; text: "↓ По пингу"; color: root.fastestFirst ? ThemeBackend.base : ThemeBackend.text; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(12) }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.fastestFirst = !root.fastestFirst }
            }
        }
        Text {
            Layout.fillWidth: true
            text: root.errorText || "TCP-пинг до сервера через текущую сеть."
            wrapMode: Text.WordWrap
            color: root.errorText ? ThemeBackend.red : ThemeBackend.subtext0
            font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(11)
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: root.s(7)
            model: root.filtered
            ScrollBar.vertical: ScrollBar { }
            delegate: Rectangle {
                id: row
                required property var modelData
                width: list.width
                height: root.s(62)
                radius: ThemeBackend.borderRadius
                readonly property bool current: VpnStatus.connected && modelData.id === VpnStatus.serverId
                color: current ? Qt.tint(ThemeBackend.surface0, Qt.rgba(ThemeBackend.blue.r, ThemeBackend.blue.g, ThemeBackend.blue.b, 0.12)) : ThemeBackend.surface0
                border.width: current ? 1 : 0
                border.color: ThemeBackend.blue
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: root.s(15)
                    anchors.rightMargin: root.s(15)
                    spacing: root.s(12)
                    Rectangle {
                        implicitWidth: root.s(34); implicitHeight: root.s(34); radius: width / 2
                        color: row.current ? ThemeBackend.blue : ThemeBackend.surface1
                        Text { anchors.centerIn: parent; text: row.current ? "✓" : "󰍎"; color: row.current ? ThemeBackend.base : ThemeBackend.subtext1; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(17) }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: root.s(4)
                        Text { Layout.fillWidth: true; text: row.modelData.name; elide: Text.ElideRight; color: ThemeBackend.text; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(13); font.bold: true }
                        Text { text: row.modelData.subscription + (row.current ? " · Подключено" : ""); color: row.current ? ThemeBackend.blue : ThemeBackend.subtext0; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(10) }
                    }
                    Rectangle {
                        implicitWidth: root.s(90); implicitHeight: root.s(28); radius: height / 2
                        readonly property color latencyColor: !row.modelData.ping ? ThemeBackend.subtext0 : row.modelData.ping < 100 ? ThemeBackend.green : row.modelData.ping < 250 ? ThemeBackend.yellow : ThemeBackend.red
                        color: Qt.rgba(latencyColor.r, latencyColor.g, latencyColor.b, 0.1)
                        Text { anchors.centerIn: parent; text: row.modelData.ping ? row.modelData.ping + " мс" : row.modelData.tested ? "Нет ответа" : "—"; color: parent.latencyColor; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(11); font.bold: true }
                    }
                }
            }
            Text { anchors.centerIn: parent; visible: !reader.running && root.filtered.length === 0; text: "Локации не найдены"; color: ThemeBackend.subtext0; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(14) }
        }
        RowLayout {
            Layout.fillWidth: true
            Text { text: root.updated ? "Проверено: " + new Date(root.updated * 1000).toLocaleTimeString(Qt.locale("ru_RU"), "HH:mm") : "Пинг ещё не проверен"; color: ThemeBackend.subtext0; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(10) }
            Item { Layout.fillWidth: true }
            Text { text: "Выбрать сервер в Happ ↗"; color: ThemeBackend.blue; font.family: ThemeBackend.fontFamily; font.pixelSize: root.s(11); MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: VpnStatus.openHapp() } }
        }
    }
}
