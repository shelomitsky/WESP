"""Exercise the actual QML command quoting through Node and a POSIX shell."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class CommandArgumentsTest(unittest.TestCase):
    def test_shell_keeps_argument_bytes_and_does_not_execute_embedded_commands(self):
        script=Path(__file__).with_name('test_queue.js')
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'executed'
            values=['', 'a b', "host'; echo BAD; #", 'строка\nвторая строка',
                    '"double quotes" \\ backslash %s',
                    '$(touch '+str(marker)+')', '`touch '+str(marker)+'`',
                    "'; touch "+str(marker)+"; #"]
            result=subprocess.run(['node',str(script),'--quote',json.dumps(values)],
                                  capture_output=True,text=True,check=True,timeout=10)
            quoted=json.loads(result.stdout)
            self.assertEqual(len(quoted),len(values))
            for value,argument in zip(values,quoted):
                result=subprocess.run(['/bin/sh','-c','printf %s '+argument],
                                      capture_output=True,text=True,check=True,timeout=5)
                self.assertEqual(result.stdout,value)
            self.assertFalse(marker.exists(),'quoted values executed as shell code')
