pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "Commands.js" as Commands

PlasmoidItem {
    id: root
    property int currentBrightness: 128
    property bool isOn: false
    property bool online: false
    property bool busy: false
    property string errorText: ""
    property string host: ""
    property string transport: "usb"
    property bool kdeEnabled: true
    property bool volumeEnabled: true
    property bool notifyEnabled: true
    property bool equalizerEnabled: false
    property int equalizerDecayMs: 250
    property int queuedDecayMs: 250
    property int sensitivity: 100
    property int noiseGate: 6
    property int attackMs: 0
    property string equalizerPalette: "classic"
    property var wallpaperColors: ["#00b482", "#b4dc00", "#ff0f0f"]
    property string wallpaperStatus: i18nd("plasma_applet_org.wledcontrol.desktop", "Picking wallpaper colors…")
    property string notifyStyle: "flash"
    property string notifyColor: "#8000ff"
    property int notifyStrength: 60
    property bool settingsExpanded: false
    property int settingsPage: 0
    property var pendingTuning: ({})
    property bool reverseFirst: false
    property bool reverseSecond: false
    property string equalizerMessage: ""
    property int notifications: 0
    property var ports: []
    property string selectedPort: ""
    property int ledCount: 0
    property var firmwareJob: ({stage: "idle"})
    readonly property bool firmwareBusy: ["starting", "tools", "download", "detecting", "backup", "writing", "connecting"].indexOf(firmwareJob.stage) >= 0
    property bool firmwareConfirmed: false
    property var setupEndpoint: ({})
    property string pendingSetupAction: ""
    property var receiverInfo: ({})
    property var receiverOutputs: []
    property int receiverCurrentBudget: 500
    property string receiverSsid: ""
    property string receiverPassword: ""
    property bool receiverNetworkDirty: false

    function editOutput(index,key,value) {
        var copy=JSON.parse(JSON.stringify(receiverOutputs));
        copy[index][key]=value; receiverOutputs=copy;
    }
    function setupRequest(action) {
        if (busy || firmwareBusy) return;
        if (!setupEndpoint.url) {
            pendingSetupAction=action;
            request(["receiver-setup-link"]);
            return;
        }
        var payload={action:action,port:selectedPort,mac:receiverInfo.mac || ""};
        if (action === "configure") {
            payload.outputs=receiverOutputs;
            payload.max_milliamps=root.receiverCurrentBudget;
            if (root.receiverNetworkDirty && root.receiverSsid.length) {
                payload.ssid=root.receiverSsid; payload.password=root.receiverPassword;
            }
        }
        var xhr=new XMLHttpRequest();
        busy=true;
        xhr.onreadystatechange=function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return;
            try {
                var reply=JSON.parse(xhr.responseText);
                if (!reply.ok) throw new Error("setup failed");
                receiverInfo=reply.receiver;
                if (action !== "status" && action !== "wifi") {
                    receiverOutputs=JSON.parse(JSON.stringify(receiverInfo.outputs || []));
                    receiverCurrentBudget=receiverInfo.max_milliamps || 500;
                }
                if (action === "configure") {
                    root.receiverPassword="";
                    root.receiverNetworkDirty=false;
                }
                errorText="";
            } catch(e) {
                errorText=i18nd("plasma_applet_org.wledcontrol.desktop", "Could not configure the receiver. Check the USB connection, GPIOs and network settings.");
                setupEndpoint=({});
            }
            busy=false;
            if (action === "configure" || action === "wifi") request(["status"]);
        };
        xhr.open("POST",setupEndpoint.url);
        xhr.setRequestHeader("Content-Type","application/json");
        xhr.setRequestHeader("Authorization","Bearer "+setupEndpoint.bearer);
        xhr.send(JSON.stringify(payload));
    }
    property var sections: []
    property var draftSections: []
    property bool layoutDirty: false
    property var queue: []
    property var activeCommand: []
    property int queuedBrightness: 128

    readonly property bool lightTheme: (0.2126 * Kirigami.Theme.backgroundColor.r
                                       + 0.7152 * Kirigami.Theme.backgroundColor.g
                                       + 0.0722 * Kirigami.Theme.backgroundColor.b) > 0.5
    readonly property url controlIcon: Qt.resolvedUrl(root.lightTheme
        ? "../images/wled-control-light.svg" : "../images/wled-control.svg")
    Plasmoid.icon: root.controlIcon
    preferredRepresentation: compactRepresentation
    toolTipMainText: "WESP"
    toolTipSubText: !online ? i18nd("plasma_applet_org.wledcontrol.desktop", "No connection to the lighting") : isOn ? i18nd("plasma_applet_org.wledcontrol.desktop", "Brightness: %1%", Math.round(currentBrightness * 100 / 255)) : i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting is off")

    function editSection(index, key, value) {
        var copy = JSON.parse(JSON.stringify(draftSections));
        copy[index][key] = value;
        layoutDirty = true;
        draftSections = copy;
    }
    function addSection() {
        var copy = JSON.parse(JSON.stringify(draftSections));
        var start = 0;
        for (var i = 0; i < copy.length; i++) start = Math.max(start, copy[i].start + copy[i].count);
        if (start >= ledCount) { errorText = i18nd("plasma_applet_org.wledcontrol.desktop", "All LEDs are assigned. Shorten a section before adding another."); return; }
        copy.push({id: "section-" + Date.now(), name: i18nd("plasma_applet_org.wledcontrol.desktop", "Strip %1", copy.length + 1), start: start,
                   count: ledCount - start, reverse: false, placement: "custom"});
        layoutDirty = true;
        draftSections = copy;
    }
    function queueSetting(key, value) {
        var pending = JSON.parse(JSON.stringify(pendingTuning));
        pending[key] = String(value);
        pendingTuning = pending;
        tuningDelay.restart();
    }
    function request(args) {
        if (args[0] === "status" && (busy || firmwareBusy)) return;
        Commands.enqueue(queue, args);
        dispatch();
    }
    function dispatch() {
        if (busy || !queue.length) return;
        activeCommand = queue.shift();
        busy = true;
        var source = '"$HOME/.local/bin/wled-control"' ;
        for (var i = 0; i < activeCommand.length; i++) source += " " + Commands.quote(activeCommand[i]);
        runner.connectSource(source);
    }
    function acceptResult(data) {
        if (data.setup && data.setup.url) {
            setupEndpoint=data.setup;
            var action=pendingSetupAction; pendingSetupAction="";
            if (action) Qt.callLater(function(){root.setupRequest(action);});
        }
        if (data.firmware) {
            var previous = firmwareJob.stage;
            firmwareJob = data.firmware;
            if (previous !== firmwareJob.stage) firmwareConfirmed = false;
            if (firmwareJob.stage === "flashed" && previous !== "flashed") {
                if (firmwareJob.flavor === "wesp") {
                    root.settingsExpanded=true; root.settingsPage=2;
                    root.request(["firmware-native-ready",firmwareJob.token]);
                } else root.request(["firmware-connect", firmwareJob.token]);
            }
        }
        if (data.wallpaper) {
            wallpaperStatus = data.wallpaper.status;
            wallpaperColors = data.wallpaper.colors.map(function(rgb) { return Qt.rgba(rgb[0]/255, rgb[1]/255, rgb[2]/255, 1); });
        }
        if (data.ports) ports = data.ports;
        if (data.settings) {
            sensitivity = data.settings.equalizer_sensitivity === undefined ? 100 : data.settings.equalizer_sensitivity;
            noiseGate = data.settings.equalizer_gate === undefined ? 6 : data.settings.equalizer_gate;
            attackMs = data.settings.equalizer_attack_ms === undefined ? 0 : data.settings.equalizer_attack_ms;
            equalizerPalette = data.settings.equalizer_palette || "classic";
            notifyStyle = data.settings.notify_style || "flash";
            notifyColor = data.settings.notify_color || "#8000ff";
            notifyStrength = data.settings.notify_strength === undefined ? 60 : data.settings.notify_strength;
            var controller = data.settings.controller;
            ledCount = controller ? controller.count : 0;
            if (controller && (!selectedPort || activeCommand[0] === "enroll")) selectedPort = controller.port;
            sections = data.settings.sections || [];
            if (!layoutDirty) draftSections = JSON.parse(JSON.stringify(sections));
            host = data.settings.host;
            transport = data.settings.transport || "usb";
            kdeEnabled = data.settings.kde;
            volumeEnabled = data.settings.volume;
            notifyEnabled = data.settings.notify;
            equalizerEnabled = data.settings.equalizer === true;
            equalizerDecayMs = typeof data.settings.equalizer_decay_ms === "number" ? data.settings.equalizer_decay_ms : 250;
            reverseFirst = data.settings.reverse_first === true;
            reverseSecond = data.settings.reverse_second === true;
        }
        if (data.equalizer) equalizerMessage = data.equalizer.message || "";
        if (data.state) {
            online = true;
            currentBrightness = data.state.bri;
            isOn = data.state.on;
        }
        if (typeof data.notifications === "number") notifications = data.notifications;
    }
    P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: function(sourceName, data) {
            disconnectSource(sourceName);
            var refresh = root.activeCommand[0] !== "status" && root.activeCommand[0] !== "receiver-setup-link" && root.activeCommand[0].indexOf("firmware-") !== 0;
            try {
                var result = JSON.parse(data["stdout"]);
                root.acceptResult(result);
                if (result.ok && data["exit code"] === 0) {
                    if (root.activeCommand[0] === "layout" || root.activeCommand[0] === "enroll" || root.activeCommand[0] === "firmware-connect") {
                        root.layoutDirty = false;
                        root.draftSections = JSON.parse(JSON.stringify(root.sections));
                    }
                    root.errorText = result.warning || "";
                } else {
                    root.online = false;
                    root.errorText = result.error || i18nd("plasma_applet_org.wledcontrol.desktop", "Could not execute the command");
                    refresh = false;
                    root.queue = [];
                }
            } catch (e) {
                root.online = false;
                root.errorText = i18nd("plasma_applet_org.wledcontrol.desktop", "Could not read the response. Try reconnecting.");
                refresh = false;
                root.queue = [];
                console.warn("WLED helper returned an invalid response");
            }
            root.busy = false;
            if (root.queue.length) root.dispatch();
            else if (refresh) root.request(["status"]);
        }
    }
    Component.onCompleted: { request(["firmware-status"]); request(["ports"]); request(["status"]); }
    Timer {
        interval: 1500
        repeat: true
        running: root.firmwareBusy
        onTriggered: root.request(["firmware-status"])
    }
    Timer {
        interval: root.expanded ? 5000 : 30000
        repeat: true
        running: true
        onTriggered: { if (!root.firmwareBusy) root.request(["status"]); }
    }
    Timer {
        id: brightnessDelay
        interval: 120
        onTriggered: root.request(["brightness", String(root.queuedBrightness)])
    }
    Timer {
        id: decayDelay
        interval: 180
        onTriggered: root.request(["setting", "equalizer_decay_ms", String(root.queuedDecayMs)])
    }
    Timer {
        id: tuningDelay
        interval: 180
        onTriggered: {
            var pending = root.pendingTuning;
            root.pendingTuning = {};
            for (var key in pending) root.request(["setting", key, pending[key]]);
        }
    }
    compactRepresentation: Item {
        Kirigami.Icon {
            anchors.fill: parent
            source: root.online ? root.controlIcon : "network-disconnect"
            opacity: root.online && root.isOn ? 1 : 0.5
            active: compactMouse.containsMouse
        }
        MouseArea {
            id: compactMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.expanded = !root.expanded
        }
    }
    fullRepresentation: QQC2.ScrollView {
        id: popup
        implicitWidth: Kirigami.Units.gridUnit * 28
        implicitHeight: Math.min(panel.implicitHeight + topPadding + bottomPadding, Kirigami.Units.gridUnit * 40)
        Layout.minimumWidth: Kirigami.Units.gridUnit * 18
        leftPadding: Kirigami.Units.smallSpacing
        topPadding: Kirigami.Units.smallSpacing
        bottomPadding: Kirigami.Units.smallSpacing
        rightPadding: Kirigami.Units.smallSpacing + (verticalBar.visible ? verticalBar.width : 0)
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
        QQC2.ScrollBar.vertical: QQC2.ScrollBar {
            id: verticalBar
            policy: QQC2.ScrollBar.AsNeeded
        }
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
        id: panel
        width: popup.availableWidth
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Kirigami.Icon {
                source: root.controlIcon
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Kirigami.Heading { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting"); level: 3 }
                QQC2.Label {
                    text: root.busy ? i18nd("plasma_applet_org.wledcontrol.desktop", "Updating…") : !root.online ? i18nd("plasma_applet_org.wledcontrol.desktop", "Disconnected") : root.isOn ? i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting is on") : i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting is off")
                    opacity: 0.7
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                }
            }
            QQC2.Switch {
                checked: root.isOn
                enabled: root.online && !root.busy
                QQC2.ToolTip.text: i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting power")
                QQC2.ToolTip.visible: hovered
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting power")
                onClicked: root.request(["power", checked ? "true" : "false"])
            }
        }
        RowLayout {
            Layout.fillWidth: true
            QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Brightness"); Layout.fillWidth: true }
            QQC2.Label { text: Math.round(briSlider.value * 100 / 255) + "%" }
        }
        QQC2.Slider {
            id: briSlider
            Layout.fillWidth: true
            from: 1
            to: 255
            stepSize: 1
            enabled: root.online && root.isOn
            Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Lighting brightness")
            onMoved: {
                root.queuedBrightness = Math.round(value);
                brightnessDelay.restart();
            }
            onPressedChanged: {
                if (!pressed && brightnessDelay.running) {
                    brightnessDelay.stop();
                    root.request(["brightness", String(root.queuedBrightness)]);
                }
            }
        }
        Binding {
            target: briSlider
            property: "value"
            value: root.currentBrightness
            when: !briSlider.pressed && !root.busy && !brightnessDelay.running
            restoreMode: Binding.RestoreBindingOrValue
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: root.errorText.length > 0
            type: Kirigami.MessageType.Warning
            text: root.errorText
        }
        QQC2.Button {
            visible: !root.online
            Layout.fillWidth: true
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "Reconnect")
            icon.name: "view-refresh"
            enabled: !root.busy
            onClicked: root.request(["status"])
        }
        Kirigami.Separator { Layout.fillWidth: true }
        QQC2.CheckBox {
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "Equalizer — react to music")
            checked: root.equalizerEnabled
            enabled: !root.busy
            onClicked: root.request(["setting", "equalizer", checked ? "true" : "false"])
        }
        QQC2.Label {
            visible: root.equalizerEnabled && !root.settingsExpanded
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: root.equalizerMessage || i18nd("plasma_applet_org.wledcontrol.desktop", "Desktop audio · smooth decay")
            opacity: 0.7
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
        ColumnLayout {
            visible: root.equalizerEnabled && root.transport === "usb" && !root.settingsExpanded
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Sensitivity"); Layout.fillWidth: true }
                QQC2.Label { text: Math.round(sensitivitySlider.value) + "%" }
            }
            QQC2.Slider {
                id: sensitivitySlider
                Layout.fillWidth: true
                from: 50; to: 200; stepSize: 5
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Sensitivity")
                onMoved: root.queueSetting("equalizer_sensitivity", Math.round(value))
            }
            Binding {
                target: sensitivitySlider; property: "value"; value: root.sensitivity
                when: !sensitivitySlider.pressed && !root.busy && !tuningDelay.running
                restoreMode: Binding.RestoreBindingOrValue
            }
        }
        RowLayout {
            visible: root.equalizerEnabled && root.transport === "usb" && !root.settingsExpanded
            Layout.fillWidth: true
            QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Decay"); Layout.fillWidth: true }
            QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "%1 ms", Math.round(decaySlider.value)) }
        }
        QQC2.Slider {
            id: decaySlider
            visible: root.equalizerEnabled && root.transport === "usb" && !root.settingsExpanded
            Layout.fillWidth: true
            from: 80
            to: 600
            stepSize: 10
            Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Equalizer decay")
            onMoved: {
                root.queuedDecayMs = Math.round(value);
                decayDelay.restart();
            }
            onPressedChanged: {
                if (!pressed && decayDelay.running) {
                    decayDelay.stop();
                    root.request(["setting", "equalizer_decay_ms", String(root.queuedDecayMs)]);
                }
            }
        }
        Binding {
            target: decaySlider
            property: "value"
            value: root.equalizerDecayMs
            when: !decaySlider.pressed && !root.busy && !decayDelay.running
            restoreMode: Binding.RestoreBindingOrValue
        }
        QQC2.Label {
            visible: root.equalizerEnabled && root.transport === "usb" && !root.settingsExpanded
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "Higher values soften the fall. Beat response stays fast.")
            opacity: 0.7
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
        QQC2.CheckBox {
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "KDE accent color")
            visible: !root.settingsExpanded
            checked: root.kdeEnabled
            enabled: !root.busy
            onClicked: root.request(["setting", "kde", checked ? "true" : "false"])
        }
        RowLayout {
            visible: root.notifications > 0
            Layout.fillWidth: true
            QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Active notifications: %1", root.notifications); Layout.fillWidth: true }
            QQC2.ToolButton { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Clear"); onClicked: root.request(["clear"]) }
        }
        QQC2.ToolButton {
            Layout.fillWidth: true
            text: checked ? i18nd("plasma_applet_org.wledcontrol.desktop", "Back to controls") : i18nd("plasma_applet_org.wledcontrol.desktop", "Configure lighting…")
            checkable: true
            checked: root.settingsExpanded
            onToggled: root.settingsExpanded = checked
        }
        QQC2.TabBar {
            visible: root.settingsExpanded
            Layout.fillWidth: true
            currentIndex: root.settingsPage
            onCurrentIndexChanged: root.settingsPage = currentIndex
            QQC2.TabButton { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Music") }
            QQC2.TabButton { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Signals") }
            QQC2.TabButton { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Strips") }
        }
        QQC2.GroupBox {
            title: i18nd("plasma_applet_org.wledcontrol.desktop", "Music response")
            visible: root.settingsExpanded && root.settingsPage === 0
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            contentItem: ColumnLayout {
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Equalizer palette") }
                QQC2.ComboBox {
                    id: palettePicker
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    model: [i18nd("plasma_applet_org.wledcontrol.desktop", "Classic"), i18nd("plasma_applet_org.wledcontrol.desktop", "Fire"), i18nd("plasma_applet_org.wledcontrol.desktop", "Ocean"), i18nd("plasma_applet_org.wledcontrol.desktop", "Violet"), i18nd("plasma_applet_org.wledcontrol.desktop", "Rainbow"), i18nd("plasma_applet_org.wledcontrol.desktop", "From wallpaper")]
                    property var keys: ["classic", "fire", "ocean", "violet", "rainbow", "wallpaper"]
                    property var previews: [
                        ["#00b482", "#b4dc00", "#ff0f0f"],
                        ["#ff1800", "#ff6e00", "#ffe678"],
                        ["#0028ff", "#00aaff", "#64ffdc"],
                        ["#4600ff", "#be00ff", "#ff50a0"],
                        ["#ff0000", "#ffbe00", "#00dc3c", "#0096ff", "#9600ff"]
                    ]
                    currentIndex: Math.max(0, keys.indexOf(root.equalizerPalette))
                    enabled: !root.busy
                    Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Equalizer palette")
                    onActivated: root.request(["setting", "equalizer_palette", keys[currentIndex]])
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Repeater {
                        model: root.equalizerPalette === "wallpaper" ? root.wallpaperColors : palettePicker.previews[palettePicker.currentIndex]
                        Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 8
                            color: modelData
                        }
                    }
                }
                QQC2.Label {
                    visible: root.equalizerPalette === "wallpaper"
                    text: root.wallpaperStatus
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.7
                }
        ColumnLayout {
            visible: true
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Attack"); Layout.fillWidth: true }
                QQC2.Label { text: attackSlider.value === 0 ? i18nd("plasma_applet_org.wledcontrol.desktop", "Fast") : i18nd("plasma_applet_org.wledcontrol.desktop", "%1 ms", Math.round(attackSlider.value)) }
            }
            QQC2.Slider {
                id: attackSlider
                Layout.fillWidth: true
                from: 0; to: 300; stepSize: 20
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Attack")
                onMoved: root.queueSetting("equalizer_attack_ms", Math.round(value))
            }
            Binding {
                target: attackSlider; property: "value"; value: root.attackMs
                when: !attackSlider.pressed && !root.busy && !tuningDelay.running
                restoreMode: Binding.RestoreBindingOrValue
            }
        }
        ColumnLayout {
            visible: true
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Noise gate"); Layout.fillWidth: true }
                QQC2.Label { text: (gateSlider.value / 10).toFixed(1) + "%" }
            }
            QQC2.Slider {
                id: gateSlider
                Layout.fillWidth: true
                from: 0; to: 30; stepSize: 1
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Noise gate")
                onMoved: root.queueSetting("equalizer_gate", Math.round(value))
            }
            Binding {
                target: gateSlider; property: "value"; value: root.noiseGate
                when: !gateSlider.pressed && !root.busy && !tuningDelay.running
                restoreMode: Binding.RestoreBindingOrValue
            }
        }
                QQC2.Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Attack softens the rise to a peak. The noise gate rejects quiet background noise.")
                    opacity: 0.7
                }
            }
        }
        QQC2.GroupBox {
            title: i18nd("plasma_applet_org.wledcontrol.desktop", "Notifications and volume")
            visible: root.settingsExpanded && root.settingsPage === 1
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            contentItem: ColumnLayout {
                QQC2.CheckBox {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Notifications")
                    checked: root.notifyEnabled
                    enabled: !root.busy
                    onClicked: root.request(["setting", "notify", checked ? "true" : "false"])
                }
                QQC2.ComboBox {
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    model: [i18nd("plasma_applet_org.wledcontrol.desktop", "Two flashes"), i18nd("plasma_applet_org.wledcontrol.desktop", "Gentle pulse"), i18nd("plasma_applet_org.wledcontrol.desktop", "Constant tint"), i18nd("plasma_applet_org.wledcontrol.desktop", "One LED")]
                    currentIndex: ["flash", "pulse", "tint", "pixel"].indexOf(root.notifyStyle)
                    Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Notification style")
                    onActivated: root.request(["setting", "notify_style", ["flash", "pulse", "tint", "pixel"][currentIndex]])
                }
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle {
                        color: root.notifyColor
                        Layout.preferredWidth: Kirigami.Units.gridUnit
                        Layout.preferredHeight: Kirigami.Units.gridUnit
                        radius: 3
                    }
                    QQC2.ComboBox {
                        Layout.fillWidth: true; Layout.minimumWidth: 0
                        model: [i18nd("plasma_applet_org.wledcontrol.desktop", "Purple"), i18nd("plasma_applet_org.wledcontrol.desktop", "Blue"), i18nd("plasma_applet_org.wledcontrol.desktop", "Warm white"), i18nd("plasma_applet_org.wledcontrol.desktop", "Orange"), i18nd("plasma_applet_org.wledcontrol.desktop", "Green")]
                        property var colors: ["#8000ff", "#00aaff", "#ffcc88", "#ff8000", "#00cc66"]
                        currentIndex: colors.indexOf(root.notifyColor)
                        displayText: currentIndex >= 0 ? currentText : i18nd("plasma_applet_org.wledcontrol.desktop", "Custom color")
                        Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Notification color")
                        onActivated: root.request(["setting", "notify_color", colors[currentIndex]])
                    }
                }
        ColumnLayout {
            visible: true
            Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Intensity"); Layout.fillWidth: true }
                QQC2.Label { text: Math.round(strengthSlider.value) + "%" }
            }
            QQC2.Slider {
                id: strengthSlider
                Layout.fillWidth: true
                from: 10; to: 100; stepSize: 5
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Intensity")
                onMoved: root.queueSetting("notify_strength", Math.round(value))
            }
            Binding {
                target: strengthSlider; property: "value"; value: root.notifyStrength
                when: !strengthSlider.pressed && !root.busy && !tuningDelay.running
                restoreMode: Binding.RestoreBindingOrValue
            }
        }
                QQC2.Button {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Preview effect")
                    Layout.fillWidth: true
                    enabled: root.notifyEnabled && root.online && root.isOn && !root.busy
                    onClicked: root.request(["notify-preview"])
                }
                QQC2.Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Flashes end automatically. Pulse and tint remain while a notification is active.")
                    opacity: 0.7
                }
                QQC2.CheckBox {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Volume indicator")
                    checked: root.volumeEnabled
                    enabled: !root.busy
                    onClicked: root.request(["setting", "volume", checked ? "true" : "false"])
                }
            }
        }
        QQC2.GroupBox {
            title: i18nd("plasma_applet_org.wledcontrol.desktop", "Device and strips")
            visible: root.settingsExpanded && root.settingsPage === 2
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            contentItem: ColumnLayout {
                RowLayout {
                    QQC2.ComboBox {
                        enabled: !root.firmwareBusy && root.firmwareJob.stage !== "prepared"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        model: root.ports
                        textRole: "label"
                        displayText: currentIndex >= 0 ? currentText : root.selectedPort || i18nd("plasma_applet_org.wledcontrol.desktop", "Select a USB port")
                        onActivated: root.selectedPort = root.ports[currentIndex].port
                    }
                    QQC2.Button { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Find"); enabled: !root.busy && !root.firmwareBusy; onClicked: root.request(["ports"]) }
                }
                QQC2.Button {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Connect selected ESP")
                    Layout.fillWidth: true
                    enabled: root.selectedPort.length > 0 && !root.busy && !root.firmwareBusy
                    onClicked: root.request(["enroll", root.selectedPort])
                }
                QQC2.Button {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Install WESP firmware (USB + Wi-Fi)")
                    Layout.fillWidth: true
                    enabled: root.selectedPort.length > 0 && !root.busy && !root.firmwareBusy && root.firmwareJob.stage !== "prepared"
                    onClicked: root.request(["firmware-prepare-native",root.selectedPort])
                }
                QQC2.Button {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Read WESP receiver")
                    Layout.fillWidth:true
                    enabled: root.selectedPort.length > 0 && !root.busy && !root.firmwareBusy
                    onClicked: root.setupRequest("probe")
                }
                QQC2.GroupBox {
                    title: i18nd("plasma_applet_org.wledcontrol.desktop", "WESP receiver: outputs and Wi-Fi")
                    Layout.fillWidth: true
                    visible: !!root.receiverInfo.mac || (root.firmwareJob.flavor === "wesp" && ["flashed","installed","connected"].indexOf(root.firmwareJob.stage)>=0)
                    contentItem: ColumnLayout {
                        QQC2.Label {
                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                            text: i18nd("plasma_applet_org.wledcontrol.desktop", "Read the receiver over USB, configure the LED outputs and Wi-Fi, then verify Wi-Fi before disconnecting USB. No frames from the PC: lights off within 1.5 seconds.")
                        }
                        QQC2.Label {
                            visible: !!root.receiverInfo.mac
                            text: "ESP: "+(root.receiverInfo.mac || "")
                        }
                        Repeater {
                            model: root.receiverOutputs
                            delegate: ColumnLayout {
                                required property int index
                                required property var modelData
                                Layout.fillWidth: true
                                RowLayout {
                                    QQC2.Label { text: "GPIO" }
                                    QQC2.SpinBox { from:0; to:33; value:modelData.gpio; editable:true; enabled:!root.busy; onValueModified:root.editOutput(index,"gpio",value) }
                                    QQC2.Label { text:i18nd("plasma_applet_org.wledcontrol.desktop", "LEDs") }
                                    QQC2.SpinBox { from:1; to:1024; value:modelData.count; editable:true; enabled:!root.busy; onValueModified:root.editOutput(index,"count",value) }
                                }
                                RowLayout {
                                    QQC2.ComboBox {
                                        model:["RGB","RBG","GRB","GBR","BRG","BGR"]
                                        currentIndex:model.indexOf(modelData.order)
                                        enabled:!root.busy
                                        onActivated:root.editOutput(index,"order",currentText)
                                    }
                                    QQC2.Button {
                                        text:i18nd("plasma_applet_org.wledcontrol.desktop", "Remove output")
                                        enabled:!root.busy
                                        onClicked:{ var copy=JSON.parse(JSON.stringify(root.receiverOutputs)); copy.splice(index,1); root.receiverOutputs=copy; }
                                    }
                                }
                            }
                        }
                        QQC2.Button {
                            text:i18nd("plasma_applet_org.wledcontrol.desktop", "Add LED output")
                            enabled:!!root.receiverInfo.mac && root.receiverOutputs.length<8 && !root.busy
                            onClicked:{var copy=JSON.parse(JSON.stringify(root.receiverOutputs)); copy.push({gpio:0,count:1,order:"GRB"}); root.receiverOutputs=copy;}
                        }
                        RowLayout {
                            QQC2.Label {text:i18nd("plasma_applet_org.wledcontrol.desktop", "LED current limit, mA")}
                            QQC2.SpinBox { id:currentBudget; from:100; to:5000; stepSize:100; value:root.receiverCurrentBudget; editable:true; enabled:!root.busy; onValueModified:root.receiverCurrentBudget=value }
                        }
                        QQC2.TextField { id:wifiSsid; Layout.fillWidth:true; placeholderText:i18nd("plasma_applet_org.wledcontrol.desktop", "Wi-Fi network name (optional)"); text:root.receiverSsid; onTextEdited:{root.receiverSsid=text;root.receiverNetworkDirty=true;} enabled:!root.busy }
                        QQC2.TextField { id:wifiPassword; Layout.fillWidth:true; placeholderText:i18nd("plasma_applet_org.wledcontrol.desktop", "Wi-Fi password"); text:root.receiverPassword; onTextEdited:{root.receiverPassword=text;root.receiverNetworkDirty=true;} echoMode:TextInput.Password; enabled:!root.busy }
                        QQC2.Button {
                            text:i18nd("plasma_applet_org.wledcontrol.desktop", "Save outputs and network to ESP")
                            enabled:!!root.receiverInfo.mac && root.receiverOutputs.length>0 && !root.busy && !root.firmwareBusy
                            onClicked:root.setupRequest("configure")
                        }
                        QQC2.Label {
                            Layout.fillWidth:true; wrapMode:Text.WordWrap
                            text:root.receiverInfo.wifi && root.receiverInfo.wifi.connected
                                ? i18nd("plasma_applet_org.wledcontrol.desktop", "Wi-Fi connected: %1",root.receiverInfo.wifi.ip)
                                : i18nd("plasma_applet_org.wledcontrol.desktop", "Wi-Fi is not connected yet")
                        }
                        RowLayout {
                            QQC2.Button {text:i18nd("plasma_applet_org.wledcontrol.desktop", "Check Wi-Fi"); enabled:!!root.receiverInfo.mac && !root.busy; onClicked:root.setupRequest("status")}
                            QQC2.Button {text:i18nd("plasma_applet_org.wledcontrol.desktop", "Use Wi-Fi"); enabled:!!root.receiverInfo.mac && !root.busy && !!root.receiverInfo.wifi && root.receiverInfo.wifi.connected; onClicked:root.setupRequest("wifi")}
                        }
                    }
                }
                QQC2.Button {
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Install WLED on a new ESP")
                    Layout.fillWidth: true
                    enabled: root.selectedPort.length > 0 && !root.busy && !root.firmwareBusy && root.firmwareJob.stage !== "prepared"
                    onClicked: root.request(["firmware-prepare", root.selectedPort])
                }
                QQC2.Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    visible: root.firmwareBusy
                    text: {
                        switch(root.firmwareJob.stage) {
                        case "tools": return i18nd("plasma_applet_org.wledcontrol.desktop", "Preparing the installer…");
                        case "download": return i18nd("plasma_applet_org.wledcontrol.desktop", "Downloading verified WLED firmware…");
                        case "detecting": return i18nd("plasma_applet_org.wledcontrol.desktop", "Checking the selected ESP…");
                        case "backup": return root.firmwareJob.backup_baud === 115200
                            ? i18nd("plasma_applet_org.wledcontrol.desktop", "Saving at a compatible USB speed: %1%. This may take about ten minutes.",root.firmwareJob.percent || 0)
                            : i18nd("plasma_applet_org.wledcontrol.desktop", "Saving the original firmware: %1%. This may take several minutes.", root.firmwareJob.percent || 0);
                        case "writing": return root.firmwareJob.flavor === "wesp"
                            ? i18nd("plasma_applet_org.wledcontrol.desktop", "Installing WESP. Keep the USB cable connected…")
                            : i18nd("plasma_applet_org.wledcontrol.desktop", "Installing WLED. Keep the USB cable connected…");
                        default: return i18nd("plasma_applet_org.wledcontrol.desktop", "Starting the installer…");
                        }
                    }
                }
                QQC2.ProgressBar {
                    Layout.fillWidth: true
                    visible: root.firmwareBusy
                    indeterminate: root.firmwareJob.stage !== "backup"
                    from: 0; to: 100; value: root.firmwareJob.percent || 0
                }
                QQC2.Label {
                    visible: root.firmwareJob.stage === "prepared"
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "ESP32 · %1 · %2\nFirmware %3\nOriginal firmware saved to: %4", root.firmwareJob.port || "", root.firmwareJob.board ? root.firmwareJob.board.mac : "", (root.firmwareJob.flavor === "wesp" ? "WESP " : "WLED ")+(root.firmwareJob.version || ""), root.firmwareJob.backup || "")
                }
                QQC2.CheckBox {
                    visible: root.firmwareJob.stage === "prepared"
                    Layout.fillWidth: true
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Replace the firmware and erase all settings on this ESP")
                    checked: root.firmwareConfirmed
                    onClicked: root.firmwareConfirmed = checked
                }
                RowLayout {
                    visible: root.firmwareJob.stage === "prepared"
                    QQC2.Button {
                        text: root.firmwareJob.flavor === "wesp" ? i18nd("plasma_applet_org.wledcontrol.desktop", "Install WESP") : i18nd("plasma_applet_org.wledcontrol.desktop", "Install WLED")
                        enabled: root.firmwareConfirmed && !root.busy
                        onClicked: root.request(["firmware-install", root.firmwareJob.token])
                    }
                    QQC2.Button {
                        text: i18nd("plasma_applet_org.wledcontrol.desktop", "Cancel")
                        enabled: !root.busy
                        onClicked: root.request(["firmware-cancel", root.firmwareJob.token])
                    }
                }
                QQC2.Label {
                    visible: root.firmwareJob.stage === "failed" || ["flashed", "installed", "connected"].indexOf(root.firmwareJob.stage) >= 0
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: root.firmwareJob.stage === "failed"
                        ? i18nd("plasma_applet_org.wledcontrol.desktop", "Installation failed: %1\nBackup: %2", root.firmwareJob.error || "", root.firmwareJob.backup || "—")
                        : root.firmwareJob.flavor === "wesp"
                            ? i18nd("plasma_applet_org.wledcontrol.desktop", "WESP installed. Read the receiver above, then save its outputs and network.")
                            : i18nd("plasma_applet_org.wledcontrol.desktop", "WLED installed. Connect the controller, then set up the LED outputs in WLED before attaching a strip.")
                }
                QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "LEDs: %1", root.ledCount) }
                QQC2.Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Set the total LED count and outputs in WLED. Arrange those LEDs here.")
                    opacity: 0.7
                }
                Repeater {
                    model: root.draftSections
                    delegate: QQC2.GroupBox {
                        required property int index
                        required property var modelData
                        id: sectionEditor
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        contentItem: ColumnLayout {
                            RowLayout {
                                Layout.fillWidth: true
                                QQC2.TextField {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    text: sectionEditor.modelData.name
                                    Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Section name")
                                    onEditingFinished: if (text !== sectionEditor.modelData.name) root.editSection(sectionEditor.index,"name",text)
                                }
                                QQC2.ToolButton {
                                    text: "×"
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                                    Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                                    Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Remove section")
                                    QQC2.ToolTip.text: i18nd("plasma_applet_org.wledcontrol.desktop", "Remove section")
                                    QQC2.ToolTip.visible: hovered
                                    onClicked: {
                                        var copy = root.draftSections.slice(); copy.splice(sectionEditor.index,1);
                                        root.layoutDirty = true; root.draftSections = copy;
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Start") }
                                    QQC2.SpinBox {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        from: 1; to: Math.max(1,root.ledCount)
                                        value: sectionEditor.modelData.start + 1
                                        editable: true
                                        onValueModified: root.editSection(sectionEditor.index,"start",value-1)
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    QQC2.Label { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Length") }
                                    QQC2.SpinBox {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        from: 1; to: Math.max(1,root.ledCount)
                                        value: sectionEditor.modelData.count
                                        editable: true
                                        onValueModified: root.editSection(sectionEditor.index,"count",value)
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                QQC2.ComboBox {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    model: [i18nd("plasma_applet_org.wledcontrol.desktop", "Left"),i18nd("plasma_applet_org.wledcontrol.desktop", "Right"),i18nd("plasma_applet_org.wledcontrol.desktop", "Top"),i18nd("plasma_applet_org.wledcontrol.desktop", "Bottom"),i18nd("plasma_applet_org.wledcontrol.desktop", "Other")]
                                    currentIndex: ["left","right","top","bottom","custom"].indexOf(sectionEditor.modelData.placement)
                                    onActivated: root.editSection(sectionEditor.index,"placement",["left","right","top","bottom","custom"][currentIndex])
                                }
                                QQC2.CheckBox {
                                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Reverse")
                                    checked: sectionEditor.modelData.reverse
                                    onClicked: root.editSection(sectionEditor.index,"reverse",checked)
                                }
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    QQC2.Button { text: i18nd("plasma_applet_org.wledcontrol.desktop", "Add section"); Layout.fillWidth: true; enabled: root.ledCount > 0; onClicked: root.addSection() }
                    QQC2.Button {
                        text: i18nd("plasma_applet_org.wledcontrol.desktop", "Save layout")
                        Layout.fillWidth: true
                        enabled: root.layoutDirty && !root.busy
                        onClicked: root.request(["layout",JSON.stringify(root.draftSections)])
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: i18nd("plasma_applet_org.wledcontrol.desktop", "Numbering starts at 1. Sections must not overlap. Unassigned LEDs stay off.")
                }
            }
        }
        QQC2.ToolButton {
            id: addressToggle
            visible: root.settingsExpanded && root.settingsPage === 2 && root.transport !== "usb"
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "Device address")
            icon.name: "configure"
            checkable: true
        }
        RowLayout {
            visible: root.settingsExpanded && root.settingsPage === 2 && root.transport !== "usb" && addressToggle.checked
            Layout.fillWidth: true
            QQC2.TextField {
                id: hostField
                Layout.fillWidth: true
                text: root.host
                placeholderText: "wled.local"
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "WLED IP address or hostname")
                enabled: !root.busy
                onAccepted: root.request(["setting", "host", text])
            }
            QQC2.ToolButton {
                icon.name: "document-save"
                enabled: !root.busy
                Accessible.name: i18nd("plasma_applet_org.wledcontrol.desktop", "Save address")
                onClicked: root.request(["setting", "host", hostField.text])
            }
        }
        QQC2.Label {
            visible: root.transport === "usb"
            text: i18nd("plasma_applet_org.wledcontrol.desktop", "USB · LEDs: %1", root.ledCount)
            opacity: 0.7
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
        }
    }
}
