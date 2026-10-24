import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 1080; height: 760
    minimumWidth: 900; minimumHeight: 640
    visible: true
    title: "WESP"
    property var data: JSON.parse(bridge.dataJson)
    readonly property bool demo: data.target === "demo"
    readonly property var prefs: data.settings || ({})
    readonly property var state: data.state || ({})
    readonly property var sections: data.sections || []
    readonly property string controlTarget: bridge.commandTarget
    property int page: 0
    property var draftSections: []
    property bool layoutDirty: false
    property var outputs: []
    property bool outputsDirty: false
    property int currentBudget: 500
    property bool wifiDirty: false
    property string selectedPort: ""
    property bool replaceConfirmed: false
    property string confirmationToken: ""
    property string editingTarget: ""
    readonly property var receiver: data.receiver || ({})
    readonly property var job: data.firmware || ({})
    readonly property bool firmwareBusy: ["starting","tools","download","detecting","backup","writing","connecting"].indexOf(job.stage) >= 0
    function t(message) { return bridge.text(message); }
    function setting(key,value) { bridge.action("setting",[key,String(value)]); }
    function editSection(index,key,value) {
        var copy=JSON.parse(JSON.stringify(draftSections)); copy[index][key]=value;
        draftSections=copy; layoutDirty=true;
    }
    function editOutput(index,key,value) {
        var copy=JSON.parse(JSON.stringify(outputs)); copy[index][key]=value;
        outputs=copy; outputsDirty=true;
    }
    function setup(action) {
        var fields={port:selectedPort,mac:receiver.mac || ""};
        if(action==="configure") {
            fields.outputs=outputs; fields.max_milliamps=currentBudget;
            if(wifiDirty) { fields.ssid=ssid.text; fields.password=password.text; }
        }
        bridge.action("setup",[action,fields]);
    }
    onDataChanged: {
        var incoming=data.settings || {};
        var target=data.target+":"+((incoming.controller || {}).mac || "");
        if(editingTarget!==target) {
            brightnessDelay.stop();
            editingTarget=target; layoutDirty=false; outputsDirty=false;
            wifiDirty=false; ssid.text=""; password.text="";
        }
        if(confirmationToken!==(data.firmware || {}).token) {
            confirmationToken=(data.firmware || {}).token || ""; replaceConfirmed=false;
        }
        if(!layoutDirty) draftSections=JSON.parse(JSON.stringify(sections));
        if(!outputsDirty) { outputs=JSON.parse(JSON.stringify(receiver.outputs || []));currentBudget=receiver.max_milliamps || 500; }
        if(!selectedPort && prefs.controller) selectedPort=prefs.controller.port || "";
    }
    Connections {
        target: bridge
        function onCompleted(action,ok) {
            if(ok && action==="layout") { root.layoutDirty=false; root.draftSections=JSON.parse(JSON.stringify(root.sections)); }
            if(ok && action==="setup-configure") { password.text=""; root.wifiDirty=false; root.outputsDirty=false; root.outputs=JSON.parse(JSON.stringify(root.receiver.outputs || [])); }
            if(ok && action==="setup-probe") { root.outputsDirty=false;root.outputs=JSON.parse(JSON.stringify(root.receiver.outputs || [])); }
        }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.preferredWidth: 184; Layout.fillHeight: true
            color: root.palette.alternateBase
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 18; spacing: 10
                RowLayout {
                    Image { source:"../plasma/org.wledcontrol.desktop/contents/images/wled-control.svg"; Layout.preferredWidth:32; Layout.preferredHeight:32 }
                    Label { text:"WESP"; font.pixelSize:25; font.weight:Font.DemiBold }
                }
                Label { text:root.t("Your desktop, in light"); wrapMode:Text.WordWrap; Layout.fillWidth:true; opacity:.65; bottomPadding:24 }
                Repeater {
                    model:[root.t("Overview"),root.t("Music"),root.t("Strips"),root.t("Signals"),root.t("Connection")]
                    Button { required property int index; required property string modelData
                        text:modelData; Layout.fillWidth:true; checkable:true; checked:root.page===index
                        onClicked:root.page=index
                        background:Rectangle { color:parent.checked ? root.palette.highlight : "transparent"; radius:5 }
                        contentItem:Label { text:parent.text; color:parent.checked ? root.palette.highlightedText : root.palette.text; padding:9; leftPadding:12 }
                    }
                }
                Item { Layout.fillHeight:true }
                Button { text:root.demo ? root.t("Back to my device") : root.t("Try without an ESP"); Layout.fillWidth:true; enabled:!bridge.busy; onClicked:bridge.setDemo(!root.demo) }
                Label { text:root.demo ? root.t("Demo — your device is unchanged") : "0.2.0-alpha.9"; wrapMode:Text.WordWrap; Layout.fillWidth:true; opacity:.6 }
            }
        }
        ColumnLayout {
            Layout.fillWidth:true; Layout.fillHeight:true; Layout.margins:28; spacing:16
            RowLayout {
                Layout.fillWidth:true
                ColumnLayout {
                    Layout.fillWidth:true; spacing:3
                    Label { text:[root.t("Your lighting"),root.t("Music"),root.t("Strips"),root.t("Signals"),root.t("Connection")][root.page]; font.pixelSize:28; font.weight:Font.DemiBold }
                    Label { text:root.demo ? root.t("Demo · desktop audio · no ESP commands") : !root.data.configured ? root.t("Connect an ESP or try the demo") : root.data.online ? ((root.prefs.controller || {}).connection==="wifi" ? root.t("Connected over Wi-Fi") : root.t("Connected over USB")) : root.t("Device unavailable"); opacity:.65 }
                }
                Switch { objectName:"powerSwitch"; text:root.t("Lighting"); checked:!!root.state.on; enabled:(root.demo || root.data.online) && !bridge.busy; onClicked:bridge.action("power",[String(checked)]) }
            }
            Frame {
                Layout.fillWidth:true
                visible:!!bridge.error || !!root.data.error
                RowLayout { anchors.fill:parent
                    Label { text:bridge.error || root.data.error || ""; wrapMode:Text.WordWrap; Layout.fillWidth:true }
                    Button { text:root.t("Retry"); enabled:!bridge.busy; onClicked:bridge.action("poll",[]) }
                }
            }
            RowLayout {
                Label { text:root.t("Brightness") }
                Slider { id:brightness; objectName:"brightnessSlider"; Layout.fillWidth:true; from:1; to:255; stepSize:1; value:root.state.bri || 128; enabled:root.demo || root.data.online; onMoved:{brightnessDelay.target=root.controlTarget;brightnessDelay.amount=Math.round(value);brightnessDelay.restart();} }
                Label { text:Math.round(brightness.value*100/255)+"%"; Layout.preferredWidth:42 }
                Timer { id:brightnessDelay; property string target:""; property int amount:128; interval:120; onTriggered:bridge.actionFor(target,"brightness",[String(amount)]) }
            }
            StackLayout {
                currentIndex:root.page; Layout.fillWidth:true; Layout.fillHeight:true
                ScrollView {
                    clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:parent.width; spacing:18
                        RowLayout {
                            Layout.fillWidth:true
                            Button { objectName:"musicSceneButton";text:root.t("Music");checkable:true;checked:!!root.prefs.equalizer;enabled:root.demo || root.data.online;onClicked:bridge.action("scene",["music"]) }
                            Button { objectName:"calmSceneButton";text:root.t("Calm light");checkable:true;checked:!root.prefs.equalizer && !!root.prefs.kde;enabled:root.demo || root.data.online;onClicked:bridge.action("scene",["calm"]) }
                            Item { Layout.fillWidth:true }
                            ComboBox { enabled:!!root.prefs.equalizer;model:[root.t("Level meter"),root.t("Pulse")];currentIndex:root.prefs.music_style==="pulse" ? 1 : 0;onActivated:root.setting("music_style",currentIndex ? "pulse" : "meter") }
                            Label { text:root.demo ? root.t("Live demo") : root.t("Host frame preview"); opacity:.6 }
                        }
                        Label { text:(root.data.activity || {}).label || root.data.message || root.t("Desktop lighting"); wrapMode:Text.WordWrap; Layout.fillWidth:true; font.pixelSize:17 }
                        Label { visible:!!root.prefs.equalizer; text:root.data.message || ""; opacity:.65;wrapMode:Text.WordWrap;Layout.fillWidth:true }
                        Label { visible:!root.sections.length; text:root.t("Your strips will appear here. Open Connection to set up your ESP, or try without one."); wrapMode:Text.WordWrap; Layout.fillWidth:true; topPadding:40; bottomPadding:40 }
                        Repeater {
                            model:root.sections
                            ColumnLayout {
                                id:strip
                                required property var modelData
                                Layout.fillWidth:true; spacing:12
                                RowLayout {
                                    Layout.fillWidth:true
                                    Label { text:strip.modelData.name; font.pixelSize:17; font.weight:Font.DemiBold; Layout.fillWidth:true }
                                    Label { text:String(strip.modelData.count)+" LED  "+(strip.modelData.reverse ? "←" : "→"); opacity:.65 }
                                }
                                Canvas {
                                    Layout.fillWidth:true; Layout.preferredHeight:48
                                    property var frame:root.data.frame || ({})
                                    onFrameChanged:requestPaint()
                                    onWidthChanged:requestPaint()
                                    onPaint: {
                                        var ctx=getContext("2d"); ctx.clearRect(0,0,width,height);
                                        var n=Math.min(80,strip.modelData.count), gap=4, size=(width-(n-1)*gap)/n;
                                        var pixels=frame.pixels || [], bri=(frame.brightness === undefined ? 255 : frame.brightness)/255;
                                        for(var i=0;i<n;i++) {
                                            var p=pixels[strip.modelData.start+Math.floor(i*strip.modelData.count/n)] || [0,0,0];
                                            ctx.fillStyle=Qt.rgba(p[0]/255*bri,p[1]/255*bri,p[2]/255*bri,1);
                                            ctx.fillRect(i*(size+gap),0,size,height);
                                            ctx.strokeStyle=root.palette.mid; ctx.lineWidth=1; ctx.strokeRect(i*(size+gap)+.5,.5,size-1,height-1);
                                        }
                                    }
                                }
                            }
                        }
                        Label { text:root.demo ? root.t("Listening to the computer output. No microphone or device connection.") : root.data.frame && !root.data.frame.stale ? root.t("Calculated colors; actual delivery and power limits are separate.") : root.t("No recent frame — start music lighting to see the preview."); opacity:.6; wrapMode:Text.WordWrap; Layout.fillWidth:true }
                    }
                }
                ScrollView {
                    clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:parent.width; spacing:18
                        Switch { text:root.t("React to desktop music");checked:!!root.prefs.equalizer;onClicked:bridge.action("scene",[checked ? "music" : "calm"]) }
                        Label { text:root.t("Music style");font.pixelSize:17 }
                        ComboBox { objectName:"musicStyleCombo";Layout.fillWidth:true;model:[root.t("Level meter"),root.t("Pulse")];property var keys:["meter","pulse"];currentIndex:Math.max(0,keys.indexOf(root.prefs.music_style || "meter"));onActivated:root.setting("music_style",keys[currentIndex]) }
                        Label { text:root.t("Character");font.pixelSize:17 }
                        ComboBox { objectName:"musicPresetCombo";Layout.fillWidth:true;model:[root.t("My tuning"),root.t("Soft"),root.t("Vivid")];property var keys:["custom","soft","vivid"];currentIndex:Math.max(0,keys.indexOf(root.prefs.music_preset || "custom"));onActivated:bridge.action("music-preset",[keys[currentIndex]]) }
                        Label { text:root.t("Palette"); font.pixelSize:17 }
                        ComboBox { Layout.fillWidth:true; model:[root.t("Classic"),root.t("Fire"),root.t("Ocean"),root.t("Violet"),root.t("Rainbow"),root.t("Wallpaper colors")]; property var keys:["classic","fire","ocean","violet","rainbow","wallpaper"]; currentIndex:Math.max(0,keys.indexOf(root.prefs.equalizer_palette || "classic")); onActivated:root.setting("equalizer_palette",keys[currentIndex]) }
                        Repeater {
                            model:[{key:"equalizer_sensitivity",name:root.t("Sensitivity"),min:50,max:200,step:5,def:100,unit:"%"},{key:"equalizer_decay_ms",name:root.t("Decay"),min:80,max:600,step:10,def:250,unit:" ms"},{key:"equalizer_attack_ms",name:root.t("Attack"),min:0,max:300,step:10,def:0,unit:" ms"},{key:"equalizer_gate",name:root.t("Noise gate"),min:0,max:30,step:1,def:6,unit:""}]
                            ColumnLayout { required property var modelData; Layout.fillWidth:true
                                RowLayout { Label { text:modelData.name; Layout.fillWidth:true } Label { text:String(Math.round(tuning.value))+modelData.unit } }
                                Slider { id:tuning; Layout.fillWidth:true; from:modelData.min; to:modelData.max; stepSize:modelData.step; value:root.prefs[modelData.key] === undefined ? modelData.def : root.prefs[modelData.key]; onPressedChanged:if(!pressed)root.setting(modelData.key,Math.round(value)) }
                            }
                        }
                    }
                }
                ScrollView {
                    clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:parent.width; spacing:12
                        Label { text:root.t("Arrange your physical LED ranges and their directions."); wrapMode:Text.WordWrap; Layout.fillWidth:true }
                        Repeater {
                            model:root.draftSections
                            Frame { id:section; required property int index; required property var modelData; Layout.fillWidth:true
                                ColumnLayout { anchors.fill:parent
                                    RowLayout {
                                        TextField { text:section.modelData.name; Layout.fillWidth:true; enabled:!root.demo; onEditingFinished:root.editSection(section.index,"name",text) }
                                        Button { text:root.t("Remove"); enabled:!root.demo; onClicked:{var a=root.draftSections.slice();a.splice(section.index,1);root.draftSections=a;root.layoutDirty=true;} }
                                    }
                                    RowLayout {
                                        Label { text:root.t("Start") }
                                        SpinBox { from:1; to:1024; value:section.modelData.start+1; editable:true; enabled:!root.demo; onValueModified:root.editSection(section.index,"start",value-1) }
                                        Label { text:root.t("LEDs") }
                                        SpinBox { from:1; to:1024; value:section.modelData.count; editable:true; enabled:!root.demo; onValueModified:root.editSection(section.index,"count",value) }
                                        CheckBox { text:root.t("Reverse"); checked:section.modelData.reverse; enabled:!root.demo; onClicked:root.editSection(section.index,"reverse",checked) }
                                    }
                                    ComboBox { model:[root.t("Left"),root.t("Right"),root.t("Top"),root.t("Bottom"),root.t("Custom")]; property var keys:["left","right","top","bottom","custom"]; currentIndex:keys.indexOf(section.modelData.placement); enabled:!root.demo; onActivated:root.editSection(section.index,"placement",keys[currentIndex]) }
                                }
                            }
                        }
                        RowLayout {
                            Button { text:root.t("Add section"); enabled:!root.demo && !!root.prefs.controller; onClicked:{var a=root.draftSections.slice(),start=0;for(var i=0;i<a.length;i++)start=Math.max(start,a[i].start+a[i].count);a.push({id:"section-"+Date.now(),name:root.t("New strip"),start:start,count:1,reverse:false,placement:"custom"});root.draftSections=a;root.layoutDirty=true;} }
                            Button { text:root.t("Save layout"); enabled:root.layoutDirty && !root.demo && !bridge.busy; onClicked:bridge.action("layout",[JSON.stringify(root.draftSections)]) }
                            Button { text:root.t("Cancel"); enabled:root.layoutDirty; onClicked:{root.layoutDirty=false;root.draftSections=JSON.parse(JSON.stringify(root.sections));} }
                        }
                    }
                }
                ScrollView {
                    clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:parent.width; spacing:18; enabled:!root.demo
                        Switch { text:root.t("Volume indicator"); checked:!!root.prefs.volume; onClicked:root.setting("volume",checked) }
                        Switch { text:root.t("Notification signals"); checked:!!root.prefs.notify; onClicked:root.setting("notify",checked) }
                        ComboBox { Layout.fillWidth:true; model:[root.t("Two flashes"),root.t("Gentle pulse"),root.t("Tint"),root.t("Marker pixel")]; property var keys:["flash","pulse","tint","pixel"]; currentIndex:Math.max(0,keys.indexOf(root.prefs.notify_style)); onActivated:root.setting("notify_style",keys[currentIndex]) }
                        RowLayout { Label { text:root.t("Color") } TextField { text:root.prefs.notify_color || "#8000ff"; onEditingFinished:root.setting("notify_color",text) } }
                        Label { text:root.t("Intensity") }
                        Slider { Layout.fillWidth:true; from:10; to:100; stepSize:5; value:root.prefs.notify_strength || 60; onPressedChanged:if(!pressed)root.setting("notify_strength",Math.round(value)) }
                        RowLayout { Button { text:root.t("Preview signal"); enabled:!!root.state.on; onClicked:bridge.action("notify-preview",[]) } Button { text:root.t("Clear signals"); onClicked:bridge.action("clear",[]) } }
                    }
                }
                ScrollView {
                    clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:parent.width; spacing:12; enabled:!root.demo
                        Label { text:root.t("Device and firmware"); font.pixelSize:19; font.weight:Font.DemiBold }
                        RowLayout {
                            ComboBox { Layout.fillWidth:true; model:root.data.ports || []; textRole:"label"; onActivated:root.selectedPort=model[currentIndex].port }
                            Button { text:root.t("Find"); enabled:!bridge.busy && !root.firmwareBusy; onClicked:bridge.action("ports",[]) }
                        }
                        Label { text:root.selectedPort; visible:!!root.selectedPort; opacity:.65 }
                        RowLayout {
                            Button { text:root.t("Connect selected ESP"); enabled:!!root.selectedPort && !bridge.busy && !root.firmwareBusy; onClicked:bridge.action("enroll",[root.selectedPort]) }
                            Button { text:root.t("Read WESP receiver"); enabled:!!root.selectedPort && !bridge.busy && !root.firmwareBusy; onClicked:root.setup("probe") }
                        }
                        Label { visible:!!root.receiver.mac; text:"ESP: "+(root.receiver.mac || ""); font.weight:Font.DemiBold }
                        Repeater {
                            model:root.outputs
                            RowLayout { id:output; required property int index; required property var modelData
                                Label { text:"GPIO" }
                                SpinBox { from:0;to:39;value:output.modelData.gpio;editable:true;onValueModified:root.editOutput(output.index,"gpio",value) }
                                Label { text:root.t("LEDs") }
                                SpinBox { from:1;to:1024;value:output.modelData.count;editable:true;onValueModified:root.editOutput(output.index,"count",value) }
                                ComboBox { model:["RGB","RBG","GRB","GBR","BRG","BGR"];currentIndex:model.indexOf(output.modelData.order);onActivated:root.editOutput(output.index,"order",currentText) }
                                Button { text:root.t("Remove");onClicked:{var a=root.outputs.slice();a.splice(output.index,1);root.outputs=a;root.outputsDirty=true;} }
                            }
                        }
                        Button { text:root.t("Add LED output"); enabled:!!root.receiver.mac && root.outputs.length<8; onClicked:{var a=root.outputs.slice();a.push({gpio:0,count:1,order:"GRB"});root.outputs=a;root.outputsDirty=true;} }
                        RowLayout { Label { text:root.t("LED current limit, mA") } SpinBox { id:currentLimit;objectName:"currentLimit";from:100;to:5000;stepSize:100;value:root.currentBudget;editable:true;onValueModified:{root.currentBudget=value;root.outputsDirty=true;} } }
                        TextField { id:ssid;Layout.fillWidth:true;placeholderText:root.t("Wi-Fi network name (optional)");onTextEdited:root.wifiDirty=true }
                        TextField { id:password;objectName:"wifiPassword";Layout.fillWidth:true;placeholderText:root.t("Wi-Fi password");echoMode:TextInput.Password;onTextEdited:root.wifiDirty=true }
                        Button { text:root.t("Save outputs and network to ESP");enabled:!!root.receiver.mac && !!root.outputs.length && !bridge.busy && !root.firmwareBusy;onClicked:root.setup("configure") }
                        Label { text:root.receiver.wifi && root.receiver.wifi.connected ? root.t("Wi-Fi connected")+": "+root.receiver.wifi.ip : root.t("Wi-Fi is not connected yet"); opacity:.7 }
                        RowLayout {
                            Button { text:root.t("Check Wi-Fi");enabled:!!root.receiver.mac && !bridge.busy;onClicked:root.setup("status") }
                            Button { text:root.receiver.connection==="wifi" ? root.t("Using Wi-Fi") : root.t("Use Wi-Fi");enabled:!!root.receiver.wifi && root.receiver.wifi.connected && root.receiver.connection!=="wifi" && !bridge.busy;onClicked:root.setup("wifi") }
                        }
                        Label { text:root.t("Install on a new ESP"); font.pixelSize:19; font.weight:Font.DemiBold; topPadding:20 }
                        RowLayout {
                            Button { text:root.t("Prepare WESP firmware");enabled:!!root.selectedPort && !root.firmwareBusy && !bridge.busy;onClicked:{root.replaceConfirmed=false;bridge.action("firmware-prepare-native",[root.selectedPort]);} }
                            Button { text:root.t("Prepare WLED firmware");enabled:!!root.selectedPort && !root.firmwareBusy && !bridge.busy;onClicked:{root.replaceConfirmed=false;bridge.action("firmware-prepare",[root.selectedPort]);} }
                        }
                        Label { text:(root.job.error || root.job.stage || "")+" "+(root.job.percent === undefined ? "" : root.job.percent+"%")+"\n"+(root.job.board ? "ESP: "+root.job.board.mac+" · "+(root.job.port || "")+"\n" : "")+(root.job.backup || "");wrapMode:Text.WordWrap;Layout.fillWidth:true;visible:!!root.job.stage && root.job.stage!=="idle" }
                        CheckBox { text:root.t("Replace the firmware and erase all settings on this ESP"); visible:root.job.stage==="prepared";checked:root.replaceConfirmed;onClicked:root.replaceConfirmed=checked }
                        RowLayout {
                            Button { text:root.t("Install firmware");visible:root.job.stage==="prepared";enabled:root.replaceConfirmed && !bridge.busy;onClicked:bridge.action("firmware-install",[root.job.token]) }
                            Button { text:root.t("Cancel");visible:root.job.stage==="prepared";onClicked:bridge.action("firmware-cancel",[root.job.token]) }
                        }
                        Button { text:root.t("Finish installation");visible:root.job.stage==="flashed";onClicked:bridge.action(root.job.flavor==="wesp" ? "firmware-native-ready" : "firmware-connect",[root.job.token]) }
                    }
                }
            }
        }
    }
}
