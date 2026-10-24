#!/usr/bin/env python3
"""Exercise the shipped setup handler and form controls in real headless Qt."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QMetaObject, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression

import receiver_setup


def fixture_qml():
    source=(Path(__file__).parent/'plasma/org.wledcontrol.desktop/contents/ui/main.qml').read_text()
    properties=source[source.index('    property var setupEndpoint:'):source.index('\n    function editOutput')]
    handler=source[source.index('    function setupRequest('):source.index('    property var sections:')]
    accept=source[source.index('    function acceptResult('):source.index('    P5Support.DataSource {')]
    fields='\n'.join(next(line for line in source.splitlines() if marker in line)
                     for marker in ('id:currentBudget;', 'id:wifiSsid;', 'id:wifiPassword;'))
    label=source.index('"Save outputs and network to ESP"')
    button=source[source.rfind('QQC2.Button {',0,label):source.index('\n                        QQC2.Label {',label)]
    button=button.replace('QQC2.Button {','QQC2.Button { id:saveButton;',1)
    wifi_button=next(line for line in source.splitlines() if '"Use Wi-Fi"' in line)
    wifi_button=wifi_button.replace('QQC2.Button {','QQC2.Button { id:wifiButton;',1)
    footer_label=source.index('"USB · LEDs: %1"')
    footer=source[source.rfind('        QQC2.Label {',0,footer_label):
                  source.index('\n        }',footer_label)+len('\n        }')]
    footer=footer.replace('QQC2.Label {','QQC2.Label { id:connectionLabel;',1)
    # Test the actual label behavior without requiring Plasma theme plugins.
    footer='\n'.join(line for line in footer.splitlines() if 'Kirigami.Theme' not in line)
    # Plasma fullRepresentation is a QQmlComponent. Its IDs must stay private
    # to that component, just as they do in the real panel.
    return '''pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
Item { id:root
    property bool busy:false
    property bool firmwareBusy:false
    property string selectedPort:"/dev/ttyUSB0"
    property string errorText:""
    property string submissionError:""
    property var endpointFixture: ({})
    property string transport:"usb"
    property int ledCount:20
    property var activeCommand: []
'''+properties+'''
    function i18nd(domain,message) { return message; }
    function request(args) {
        if(args[0]==="receiver-setup-link") Qt.callLater(function(){
            root.setupEndpoint=root.endpointFixture;
            var action=root.pendingSetupAction; root.pendingSetupAction="";
            root.setupRequest(action);
        });
    }
'''+handler+'\n'+accept+'''
    property Component fullRepresentation: Item {
'''+fields+'\n'+button+'\n'+wifi_button+'\n'+footer+'''
        function enterDraft() {
            currentBudget.value=700; currentBudget.valueModified();
            wifiSsid.insert(0,"Test network"); wifiSsid.textEdited();
            wifiPassword.insert(0,"wesp-test-secret"); wifiPassword.textEdited();
        }
        function save() { saveButton.clicked(); }
        function useWifi() { wifiButton.clicked(); }
        function secretEmpty() { return wifiPassword.text.length===0; }
        function wifiButtonEnabled() { return wifiButton.enabled; }
        function wifiButtonText() { return wifiButton.text; }
        function connectionText() { return connectionLabel.text; }
    }
    Loader { id:form; sourceComponent:root.fullRepresentation }
    function enterDraft() { form.item.enterDraft(); }
    function submit() {
        try {form.item.save();} catch(e) {submissionError=e.toString();}
    }
    function hasSecret() { return !form.item.secretEmpty(); }
    function switchWifi() { form.item.useWifi(); }
    function wifiButtonEnabled() { return form.item.wifiButtonEnabled(); }
    function wifiButtonText() { return form.item.wifiButtonText(); }
    function connectionText() { return form.item.connectionText(); }
}
'''


class QmlSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.requests=[]
        self.fail_requests=False
        def callback(data):
            self.requests.append(data)
            if self.fail_requests: raise ValueError('fixture setup failure')
            return dict(mac='680947485628',outputs=data.get('outputs',[]),
                        max_milliamps=700,connection='wifi' if data.get('action')=='wifi' else 'usb',
                        wifi=dict(configured=True,connected=data.get('action')=='wifi'))
        self.bridge=receiver_setup.Bridge(self.folder.name,callback)
        endpoint=json.loads(self.bridge.path.read_text())
        self.engine=QQmlEngine()
        self.component=QQmlComponent(self.engine)
        self.component.setData(fixture_qml().encode(),QUrl('file:///wesp-setup-fixture.qml'))
        self.root=self.component.createWithInitialProperties(dict(
            endpointFixture=endpoint,setupEndpoint=endpoint,
            receiverInfo=dict(mac='680947485628',max_milliamps=500),
            receiverOutputs=[dict(gpio=2,count=10,order='GRB'),dict(gpio=4,count=10,order='GRB')]))
        self.assertIsNotNone(self.root,[e.toString() for e in self.component.errors()])
        QMetaObject.invokeMethod(self.root,'enterDraft')

    def tearDown(self):
        self.bridge.close()
        self.root=None
        self.component=None
        self.engine=None
        self.folder.cleanup()

    def submit(self,expected_requests):
        QMetaObject.invokeMethod(self.root,'submit')
        self.wait_for_requests(expected_requests)

    def wait_for_requests(self,expected_requests):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.app.processEvents()
            if self.root.property('submissionError'): break
            if len(self.requests)>=expected_requests and not self.root.property('busy'): break
            time.sleep(.005)
        self.assertEqual(self.root.property('submissionError'),'')
        self.assertEqual(len(self.requests),expected_requests)
        self.assertFalse(self.root.property('busy'))

    def test_save_reads_form_across_component_boundary_and_clears_secret(self):
        self.submit(1)
        self.assertEqual(self.requests[0],dict(action='configure',port='/dev/ttyUSB0',
            mac='680947485628',max_milliamps=700,ssid='Test network',password='wesp-test-secret',
            outputs=[dict(gpio=2,count=10,order='GRB'),dict(gpio=4,count=10,order='GRB')]))
        self.assertEqual(self.root.property('errorText'),'')
        self.assertEqual(self.root.property('receiverPassword'),'')
        # Execute inside the form scope; do not infer clearing from model data.
        self.assertFalse(QQmlExpression(self.engine.rootContext(),self.root,'hasSecret()').evaluate()[0])

    def test_failed_save_keeps_secret_for_retry(self):
        self.fail_requests=True
        self.submit(1)
        self.assertTrue(self.root.property('errorText'))
        self.assertEqual(self.root.property('receiverPassword'),'wesp-test-secret')

    def test_saving_outputs_again_does_not_replace_wifi_with_empty_password(self):
        self.submit(1)
        self.submit(2)
        self.assertNotIn('ssid',self.requests[1])
        self.assertNotIn('password',self.requests[1])

    def test_endpoint_discovery_keeps_the_pending_form_values(self):
        self.root.setProperty('setupEndpoint',{})
        self.submit(1)
        self.assertEqual(self.requests[0]['ssid'],'Test network')
        self.assertEqual(self.requests[0]['password'],'wesp-test-secret')

    def test_wifi_handoff_changes_button_and_connection_label(self):
        self.root.setProperty('receiverInfo',dict(mac='680947485628',connection='usb',
            wifi=dict(configured=True,connected=True,ip='192.0.2.2')))
        def evaluate(code):
            expression=QQmlExpression(self.engine.rootContext(),self.root,code)
            value,error=expression.evaluate()
            self.assertFalse(error)
            return value
        self.assertTrue(evaluate('wifiButtonEnabled()'))
        original_text=evaluate('wifiButtonText()')
        self.assertIn('USB',evaluate('connectionText()'))
        QMetaObject.invokeMethod(self.root,'switchWifi')
        self.wait_for_requests(1)
        self.assertEqual(self.requests[0]['action'],'wifi')
        self.assertFalse(evaluate('wifiButtonEnabled()'))
        self.assertNotEqual(evaluate('wifiButtonText()'),original_text)
        self.assertIn('Wi-Fi',evaluate('connectionText()'))
        self.assertNotIn('USB',evaluate('connectionText()'))

    def test_usb_probe_overrides_previously_selected_wifi_display(self):
        self.root.setProperty('selectedReceiverConnection','wifi')
        self.root.setProperty('receiverInfo',dict(mac='680947485628',connection='wifi'))
        request=QQmlExpression(self.engine.rootContext(),self.root,'setupRequest("probe")')
        request.evaluate()
        self.assertFalse(request.hasError())
        self.wait_for_requests(1)
        self.assertEqual(self.requests[0]['action'],'probe')
        text=QQmlExpression(self.engine.rootContext(),self.root,'connectionText()').evaluate()[0]
        self.assertIn('USB',text)
        self.assertNotIn('Wi-Fi',text)

    def test_successful_enrollment_clears_previous_receiver_display_and_secret(self):
        for action in ('enroll',):
            with self.subTest(action=action):
                self.root.setProperty('receiverInfo',dict(mac='680947485628',connection='wifi'))
                self.root.setProperty('selectedReceiverConnection','wifi')
                self.root.setProperty('receiverPassword','wesp-test-secret')
                self.root.setProperty('activeCommand',[action])
                result=QQmlExpression(self.engine.rootContext(),self.root,'acceptResult({ok:true})')
                result.evaluate()
                self.assertFalse(result.hasError())
                text=QQmlExpression(self.engine.rootContext(),self.root,'connectionText()').evaluate()[0]
                self.assertIn('USB',text)
                self.assertNotIn('Wi-Fi',text)
                self.assertEqual(self.root.property('receiverPassword'),'')

    def test_status_or_failed_enrollment_keeps_receiver_setup(self):
        for action,ok in (('status',True),('enroll',False),('firmware-connect',False)):
            with self.subTest(action=action):
                self.root.setProperty('receiverInfo',dict(mac='680947485628',connection='wifi'))
                self.root.setProperty('receiverPassword','wesp-test-secret')
                self.root.setProperty('activeCommand',[action])
                result=QQmlExpression(self.engine.rootContext(),self.root,
                    'acceptResult('+json.dumps(dict(ok=ok))+')')
                result.evaluate()
                self.assertFalse(result.hasError())
                connection=QQmlExpression(self.engine.rootContext(),self.root,'receiverInfo.connection').evaluate()[0]
                self.assertEqual(connection,'wifi')
                self.assertEqual(self.root.property('receiverPassword'),'wesp-test-secret')


if __name__=='__main__': unittest.main()
