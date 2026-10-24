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
    fields='\n'.join(next(line for line in source.splitlines() if marker in line)
                     for marker in ('id:currentBudget;', 'id:wifiSsid;', 'id:wifiPassword;'))
    label=source.index('"Save outputs and network to ESP"')
    button=source[source.rfind('QQC2.Button {',0,label):source.index('\n                        QQC2.Label {',label)]
    button=button.replace('QQC2.Button {','QQC2.Button { id:saveButton;',1)
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
'''+properties+'''
    function i18nd(domain,message) { return message; }
    function request(args) {
        if(args[0]==="receiver-setup-link") Qt.callLater(function(){
            root.setupEndpoint=root.endpointFixture;
            var action=root.pendingSetupAction; root.pendingSetupAction="";
            root.setupRequest(action);
        });
    }
'''+handler+'''
    property Component fullRepresentation: Item {
'''+fields+'\n'+button+'''
        function enterDraft() {
            currentBudget.value=700; currentBudget.valueModified();
            wifiSsid.insert(0,"Test network"); wifiSsid.textEdited();
            wifiPassword.insert(0,"wesp-test-secret"); wifiPassword.textEdited();
        }
        function save() { saveButton.clicked(); }
        function secretEmpty() { return wifiPassword.text.length===0; }
    }
    Loader { id:form; sourceComponent:root.fullRepresentation }
    function enterDraft() { form.item.enterDraft(); }
    function submit() {
        try {form.item.save();} catch(e) {submissionError=e.toString();}
    }
    function hasSecret() { return !form.item.secretEmpty(); }
}
'''


class QmlSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.requests=[]
        self.fail=False
        def callback(data):
            self.requests.append(data)
            if self.fail: raise ValueError('fixture setup failure')
            return dict(mac='680947485628',outputs=data.get('outputs',[]),
                        max_milliamps=700,wifi=dict(configured=True,connected=False))
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
        self.fail=True
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


if __name__=='__main__': unittest.main()
