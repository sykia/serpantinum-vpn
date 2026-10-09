import QtQuick
import Quickshell
import "../../../"
import "../../../reusables"
import "../../../vpn"

Item {
    id: root
    property var module: null
    property var widget: module
    readonly property var barWindow: module ? module.barWindow : null
    readonly property bool isCompact: module ? module.isCompact : false
    property real targetWidth: pill.implicitWidth + (barWindow ? barWindow.s(10) : 10)
    property bool isFaceVisible: !module || module.moduleActive
    implicitWidth: isFaceVisible ? targetWidth : 0
    implicitHeight: parent ? parent.height : 30
    ClickButton {
        id: pill
        anchors.centerIn: parent
        height: barWindow ? barWindow.s(root.isCompact ? 28 : 30) : 30
        cornerRadius: Math.max(0, ThemeBackend.borderRadius - 2)
        horizontalPadding: root.isCompact ? 10 : 12
        buttonIcon: "󰦝"
        buttonText: VpnStatus.connected ? "VPN · " + VpnStatus.location : "VPN · " + I18n.t("network.status.disconnected", "Disconnected")
        iconFontSize: 15
        textFontSize: 12
        accentColor: VpnStatus.connected ? ThemeBackend.blue : ThemeBackend.surface0
        textColor: VpnStatus.connected ? ThemeBackend.base : ThemeBackend.text
        onClicked: Quickshell.execDetached(["bash", Caching.serpantinumDir + "/scripts/qs_manager.sh", "toggle", "vpn"])
    }
}
