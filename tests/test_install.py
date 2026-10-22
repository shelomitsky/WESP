import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import manage


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,HOME=str(self.root),XDG_DATA_HOME=str(self.root/'data'),
                            XDG_STATE_HOME=str(self.root/'state'),XDG_CONFIG_HOME=str(self.root/'config'))
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_empty_home_install_and_remove_keep_user_settings(self):
        manage.install(start=False)
        self.assertTrue((self.root/'.local/bin/wled-control').is_file())
        self.assertTrue((self.root/'data/wled-control/layout.py').is_file())
        self.assertEqual(len(list((self.root/'config/systemd/user').glob('wled-control-*.service'))),6)
        config=self.root/'config/wled-control/settings.json'
        config.parent.mkdir(parents=True)
        config.write_text('{"equalizer_decay_ms":350}')
        manage.remove(start=False)
        self.assertEqual(json.loads(config.read_text())['equalizer_decay_ms'],350)
        self.assertFalse((self.root/'.local/bin/wled-control').exists())

    def test_upgrade_rollback_and_edit_guard(self):
        manage.install(start=False)
        target=self.root/'data/wled-control/control.py'
        expected=target.read_bytes()
        backup=manage.install(start=False)
        manage.rollback(backup,start=False)
        self.assertEqual(target.read_bytes(),expected)
        target.write_text('user edit')
        with self.assertRaises(ValueError):
            manage.install(start=False)
        self.assertEqual(target.read_text(),'user edit')

    def test_failure_during_first_install_leaves_no_owned_files(self):
        real=manage.atomic_write
        calls=[0]
        def fail_once(*args,**kwargs):
            calls[0]+=1
            if calls[0] == 2:
                raise OSError('simulated write failure')
            return real(*args,**kwargs)
        with patch.object(manage,'atomic_write',side_effect=fail_once):
            with self.assertRaises(OSError):
                manage.install(start=False)
        self.assertFalse((self.root/'data/wled-control/control.py').exists())
        self.assertFalse((self.root/'.local/bin/wled-control').exists())

    def test_activation_failure_removes_new_enablement_links(self):
        unitdir=self.root/'config/systemd/user'
        wants=unitdir/'graphical-session.target.wants'
        def service(*args,**kwargs):
            if args[0] in ('is-active','is-enabled'):
                return SimpleNamespace(returncode=1)
            if args[0] == 'enable' and '--now' in args:
                wants.mkdir(parents=True,exist_ok=True)
                for unit in manage.UNITS:
                    (wants/unit).symlink_to(unitdir/unit)
                raise subprocess.CalledProcessError(1,['systemctl','enable'])
            if args[0] == 'disable':
                # A missing unit may prevent removal of its enablement links.
                for unit in args[1:]:
                    if (unitdir/unit).exists():
                        (wants/unit).unlink(missing_ok=True)
            return SimpleNamespace(returncode=0)
        with patch.object(manage,'doctor',return_value=[]), \
             patch.object(manage,'systemctl',side_effect=service):
            with self.assertRaises(subprocess.CalledProcessError):
                manage.install(start=True)
        self.assertEqual(list(wants.iterdir()),[])
        self.assertFalse((self.root/'data/wled-control/control.py').exists())
