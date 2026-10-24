import json
from pathlib import Path
import socket
import tempfile
import unittest

MAC='680947485628'

class RealtimeOwnerTest(unittest.TestCase):
    def setup_owner(self):
        import control,layout,realtime_owner
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        class Device:
            expected_mac=MAC;led_count=2;connection='wifi';document={'on':True};fast_stats={}
            def __init__(self):self.frames=[];self.revoked=0
            def supports_realtime(self):return True
            def prepare_realtime(self,config):return True
            def realtime_active(self):return True
            def revoke_realtime(self):self.revoked+=1
            def send_realtime(self,*args):self.frames.append(args);return True
        device=Device();owner=realtime_owner.RealtimeOwner(Path(folder.name),lambda:device);owner.bind();self.addCleanup(owner.close)
        prefs=control.DEFAULTS|dict(controller=dict(mac=MAC,count=2,backend='wesp',connection='wifi'),sections=layout.legacy(2),equalizer=True)
        owner.prepare(prefs,{'suspended':False},False)
        sender=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);sender.setblocking(False);self.addCleanup(sender.close)
        return owner,device,sender,prefs

    def test_local_batch_collapses_to_newest_target_sample(self):
        import realtime_protocol as rt
        owner,d,s,_=self.setup_owner();now=rt.now_ns()
        for delta,value in ((-3_000_000,100),(-1_000_000,300),(-2_000_000,200)):
            s.sendto(rt.pack_local(MAC,2,now+delta,value,0),str(owner.path))
        owner.pump()
        self.assertEqual(len(d.frames),1);self.assertEqual(d.frames[0][3],300)

    def test_wrong_target_stale_and_reordered_samples_never_reach_transport(self):
        import realtime_protocol as rt
        owner,d,s,_=self.setup_owner();now=rt.now_ns()
        for mac,count,at in [('a0b7652d2050',2,now),(MAC,3,now),(MAC,2,now-200_000_000)]:
            s.sendto(rt.pack_local(mac,count,at,100,0),str(owner.path))
        owner.pump();self.assertEqual(d.frames,[])
        s.sendto(rt.pack_local(MAC,2,rt.now_ns(),100,0),str(owner.path));owner.pump()
        s.sendto(rt.pack_local(MAC,2,now,200,0),str(owner.path));owner.pump()
        self.assertEqual(len(d.frames),1)

    def test_suspend_off_and_calibration_revoke_delivery(self):
        import realtime_protocol as rt
        owner,d,s,prefs=self.setup_owner()
        for memory,calibration,on in [({'suspended':True},False,True),({'suspended':False},True,True),({'suspended':False},False,False)]:
            d.document['on']=on;owner.prepare(prefs,memory,calibration)
            s.sendto(rt.pack_local(MAC,2,rt.now_ns(),100,0),str(owner.path));owner.pump()
            self.assertEqual(d.frames,[])
        self.assertGreater(d.revoked,0)
        status=json.loads((owner.runtime/'audio-stream.json').read_text())
        self.assertTrue(status['supported']);self.assertFalse(status['active'])
        self.assertNotIn('key',status)

    def test_socket_is_private_and_failed_preparation_does_not_queue_samples(self):
        import realtime_protocol as rt
        owner,d,s,prefs=self.setup_owner()
        self.assertEqual(owner.path.stat().st_mode&0o777,0o600)
        def fail(config):raise TimeoutError('stalled TCP')
        d.prepare_realtime=fail
        with self.assertRaises(TimeoutError):owner.prepare(prefs,{},False)
        s.sendto(rt.pack_local(MAC,2,rt.now_ns(),100,0),str(owner.path));owner.pump()
        self.assertEqual(d.frames,[])

if __name__=='__main__':unittest.main()
