import unittest
import effects_config,layout,realtime_protocol as rt
from native_sim import Simulator

KEY=b'x'*32;SID=b'12345678'

def config():return effects_config.from_preferences(dict(controller={'count':2},sections=layout.legacy(2)))

class RealtimeCoreBenchTest(unittest.TestCase):
    def receiver(self):
        sim=Simulator(2);self.addCleanup(sim.close);sim.configure(config());sim.power(True)
        self.assertTrue(sim.stream(SID,100));return sim

    def test_delays_bad_auth_and_reordering_do_not_renew_core_lease(self):
        for delay in (0,20,80,100,250,500):
            with self.subTest(delay=delay):
                sim=self.receiver();packet=rt.pack_audio(KEY,SID,1,100,20000,10000)
                accepted=sim.datagrams([packet],100+delay,KEY,SID)
                self.assertEqual(accepted,delay<=80)
                self.assertEqual(sim.last_frame(),100+delay if delay<=80 else 0)
        sim=self.receiver();good=rt.pack_audio(KEY,SID,3,100,20000,10000)
        self.assertTrue(sim.datagrams([good],110,KEY,SID))
        self.assertFalse(sim.datagrams([good],120,KEY,SID))
        old=rt.pack_audio(KEY,SID,2,120,20000,10000)
        self.assertFalse(sim.datagrams([old],120,KEY,SID))
        wrong=rt.pack_audio(b'y'*32,SID,4,130,20000,10000)
        self.assertFalse(sim.datagrams([wrong],130,KEY,SID));self.assertEqual(sim.last_frame(),110)
        self.assertTrue(any(any(rgb) for rgb in sim.frame(130)))
        self.assertFalse(any(any(rgb) for rgb in sim.frame(1310)))

    def test_received_batch_renders_newest_value_and_off_revokes_grant(self):
        sim=self.receiver()
        packets=[rt.pack_audio(KEY,SID,1,100,30000,20000),rt.pack_audio(KEY,SID,2,110,0,0)]
        self.assertTrue(sim.datagrams(packets,120,KEY,SID))
        self.assertFalse(any(any(rgb) for rgb in sim.frame(120)),'queued high sample must not flash before newer silence')
        sim.power(False);sim.power(True)
        newer=rt.pack_audio(KEY,SID,3,130,30000,20000)
        self.assertFalse(sim.datagrams([newer],130,KEY,SID))
        self.assertFalse(any(any(rgb) for rgb in sim.frame(130)))

    def test_configuration_change_revokes_old_stream_without_renewing(self):
        sim=self.receiver();self.assertTrue(sim.datagrams([rt.pack_audio(KEY,SID,1,100,20000,10000)],100,KEY,SID))
        cfg=config();cfg['presets'][0]['sensitivity']=110;cfg['revision']=effects_config.revision(cfg);sim.configure(cfg)
        self.assertEqual(sim.last_frame(),100)
        self.assertFalse(sim.datagrams([rt.pack_audio(KEY,SID,2,110,30000,10000)],110,KEY,SID))

if __name__=='__main__':unittest.main()
