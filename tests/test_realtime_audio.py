import unittest


class RealtimePacketTest(unittest.TestCase):
    def test_fixed_packet_roundtrip_and_authentication(self):
        import realtime_protocol as rt
        key=bytes(range(32));sid=b'12345678'
        packet=rt.pack_audio(key,sid,7,0xfffffffe,12345,65000)
        self.assertEqual(len(packet),40)
        self.assertEqual(rt.unpack_audio(packet,key,sid),(7,0xfffffffe,12345,65000))
        for index in (0,5,12,18,25,39):
            damaged=bytearray(packet);damaged[index]^=1
            with self.assertRaises(ValueError):rt.unpack_audio(bytes(damaged),key,sid)
        with self.assertRaises(ValueError):rt.unpack_audio(packet,b'x'*32,sid)
        with self.assertRaises(ValueError):rt.unpack_audio(packet,key,b'87654321')
        for data in (packet[:-1],packet+b'x'):
            with self.assertRaises(ValueError):rt.unpack_audio(data,key,sid)

    def test_fixed_point_levels_reject_nan_and_keep_noise_gate_resolution(self):
        import realtime_protocol as rt
        self.assertEqual(rt.level(0),0);self.assertEqual(rt.level(1),65535)
        self.assertLess(abs(rt.level(.006)/65535-.006),1/65535)
        for n in (-1,2,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):rt.level(n)

    def test_local_datagram_pins_identity_and_count(self):
        import realtime_protocol as rt
        packet=rt.pack_local('680947485628',20,123456789,100,200)
        self.assertEqual(len(packet),24)
        self.assertEqual(rt.unpack_local(packet),('680947485628',20,123456789,100,200))
        for mac,count in [('bad',20),('680947485628',0),('680947485628',1025)]:
            with self.assertRaises(ValueError):rt.pack_local(mac,count,1,0,0)

    def test_constant_and_silent_inputs_use_sparse_refresh(self):
        import realtime_protocol as rt
        for levels in ((0,0),(12000,5000)):
            policy=rt.DeltaPolicy();sent=[]
            for ms in range(0,10001,10):
                if policy.eligible(*levels,ms*1000000):policy.sent(*levels,ms*1000000);sent.append(ms)
            self.assertEqual(len(sent),26)
            self.assertTrue(all(b-a==400 for a,b in zip(sent,sent[1:])))
            self.assertEqual(len(sent)*40,1040)

    def test_changes_are_prompt_and_small_jitter_is_suppressed(self):
        import realtime_protocol as rt
        p=rt.DeltaPolicy();p.sent(1000,1000,0)
        self.assertFalse(p.eligible(1010,1010,10_000_000))
        self.assertTrue(p.eligible(2000,1000,10_000_000))
        p.sent(2000,1000,10_000_000)
        self.assertFalse(p.eligible(3000,1000,15_000_000))
        self.assertTrue(p.eligible(0,0,20_000_000))

    def test_clock_sync_budget_expiry_suspend_and_wrap(self):
        import realtime_protocol as rt
        c=rt.AudioClock();base=1_000_000_000
        self.assertTrue(c.sync(base,base+20_000_000,0xfffffff0))
        self.assertEqual(c.stamp(base+30_000_000,base+30_000_000),4)
        self.assertFalse(c.sync(base,base+81_000_000,50))
        self.assertEqual(c.stamp(base+30_000_000,base+30_000_000),4)
        with self.assertRaises(ValueError):c.stamp(base+20_000_000,base+200_000_000)
        with self.assertRaises(ValueError):c.stamp(base+20_000_000,base+11_000_000_000)
        with self.assertRaises(ValueError):c.stamp(base+50_000_000,base+30_000_000)


if __name__=='__main__':unittest.main()
