import subprocess
import unittest
from unittest.mock import patch

class OutputMonitorTest(unittest.TestCase):
    def test_tracks_only_default_output_and_keeps_same_monitor_for_other_events(self):
        import audio_source
        def answer(name):return subprocess.CompletedProcess([],0,name+'\n','')
        with patch.object(audio_source.subprocess,'run',side_effect=[answer('speakers'),answer('speakers'),answer('headphones')]) as query, \
             patch.object(audio_source.threading.Thread,'start'):
            monitor=audio_source.OutputMonitor()
            self.assertEqual(monitor.source,'speakers.monitor')
            monitor.refresh();self.assertEqual(monitor.source,'speakers.monitor')
            monitor.refresh();self.assertEqual(monitor.source,'headphones.monitor')
            self.assertTrue(all(c.args[0]==['pactl','get-default-sink'] for c in query.call_args_list))

    def test_failed_or_malformed_query_keeps_last_output(self):
        import audio_source
        replies=[subprocess.CompletedProcess([],0,'speakers\n',''),subprocess.TimeoutExpired('pactl',1),subprocess.CompletedProcess([],0,'bad\nname\n','')]
        with patch.object(audio_source.subprocess,'run',side_effect=replies),patch.object(audio_source.threading.Thread,'start'):
            monitor=audio_source.OutputMonitor();monitor.refresh();monitor.refresh()
            self.assertEqual(monitor.source,'speakers.monitor')
