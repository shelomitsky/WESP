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


class UserServices:
    def __init__(self, active=(), enabled=(), fail_stop=False, activating=()):
        self.active, self.enabled = set(active), set(enabled)
        self.fail_stop = fail_stop
        self.activating = set(activating)

    def __call__(self, action, *args, check=True):
        units = set(arg for arg in args if not arg.startswith('--'))
        if action in ('is-active', 'is-enabled'):
            if action == 'is-active' and args[0] in self.activating:
                return SimpleNamespace(returncode=3, stdout='activating\n')
            states = self.active if action == 'is-active' else self.enabled
            return SimpleNamespace(returncode=0 if args[0] in states else 1, stdout='')
        if action == 'stop' and self.fail_stop:
            if self.fail_stop == 'partial':
                self.active.discard(args[0])
            if check:
                raise subprocess.CalledProcessError(1, ['systemctl', 'stop', *args])
            return SimpleNamespace(returncode=1, stdout='')
        if action == 'stop':
            self.active.difference_update(units)
            self.activating.difference_update(units)
        elif action == 'start':
            self.active.update(units)
        elif action == 'enable':
            self.enabled.update(units)
            if '--now' in args:
                self.active.update(units)
        elif action == 'disable':
            self.enabled.difference_update(units)
        return SimpleNamespace(returncode=0, stdout='')


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
        config=self.root/'config/wled-control-desktop/settings.json'
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

    def test_failed_stop_aborts_upgrade_remove_and_rollback_before_file_changes(self):
        for action in ('upgrade', 'remove', 'rollback'):
            with self.subTest(action=action):
                backup = manage.install(start=False)
                target = self.root/'data/wled-control/control.py'
                inode = target.stat().st_ino
                manifest = manage.read_manifest()
                services = UserServices(manage.UNITS, manage.UNITS, fail_stop=True)
                with patch.object(manage, 'doctor', return_value=[]), \
                     patch.object(manage, 'systemctl', side_effect=services):
                    with self.assertRaises(subprocess.CalledProcessError):
                        if action == 'upgrade':
                            manage.install(start=True)
                        elif action == 'remove':
                            manage.remove(start=True)
                        else:
                            manage.rollback(backup, start=True)
                self.assertEqual(target.stat().st_ino, inode)
                self.assertEqual(manage.read_manifest(), manifest)
                self.assertEqual(services.enabled, set(manage.UNITS))
                manage.check_owned(manifest, manage.payloads())

    def test_partial_uninstall_restores_owned_files_and_service_states(self):
        manage.install(start=False)
        manifest = manage.read_manifest()
        settings = self.root/'config/wled-control-desktop/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_bytes(b'{"equalizer_decay_ms":320}\n')
        services = UserServices(manage.UNITS[:2], manage.UNITS[:3])
        original_unlink = Path.unlink
        fail_target = self.root/'data/wled-control/equalizer.py'
        failed = []
        def unlink(path, *args, **kwargs):
            if path == fail_target and not failed:
                failed.append(True)
                raise PermissionError('injected unlink failure')
            return original_unlink(path, *args, **kwargs)
        with patch.object(manage, 'systemctl', side_effect=services), \
             patch.object(Path, 'unlink', unlink):
            with self.assertRaises(PermissionError):
                manage.remove(start=True)
        self.assertEqual(manage.read_manifest(), manifest)
        manage.check_owned(manifest, manage.payloads())
        self.assertEqual(services.active, set(manage.UNITS[:2]))
        self.assertEqual(services.enabled, set(manage.UNITS[:3]))
        self.assertEqual(settings.read_bytes(), b'{"equalizer_decay_ms":320}\n')
        manage.install(start=False)  # supported recovery remains available

    def test_normal_install_activates_a_previously_staged_install(self):
        manage.install(start=False)
        services = UserServices()
        with patch.object(manage, 'doctor', return_value=[]), \
             patch.object(manage, 'systemctl', side_effect=services):
            manage.install(start=True)
        self.assertEqual(services.active, set(manage.UNITS))
        self.assertEqual(services.enabled, set(manage.UNITS))

    def test_upgrade_preserves_an_intentionally_disabled_service(self):
        services = UserServices()
        with patch.object(manage, 'doctor', return_value=[]), \
             patch.object(manage, 'systemctl', side_effect=services):
            manage.install(start=True)
            disabled = manage.UNITS[-1]
            services.active.remove(disabled)
            services.enabled.remove(disabled)
            manage.install(start=True)
        self.assertEqual(services.active, set(manage.UNITS)-{disabled})
        self.assertEqual(services.enabled, set(manage.UNITS)-{disabled})

    def test_uninstall_cancels_activating_services_before_deleting_files(self):
        manage.install(start=False)
        services = UserServices(activating=manage.UNITS)
        with patch.object(manage, 'systemctl', side_effect=services):
            manage.remove(start=True)
        self.assertEqual(services.activating, set())

    def test_partial_rollback_stop_failure_restores_current_not_historical_activity(self):
        backup = manage.install(start=False)
        current_active = set(manage.UNITS[:2])
        services = UserServices(current_active, manage.UNITS[:3], fail_stop='partial')
        target = self.root/'data/wled-control/control.py'
        inode = target.stat().st_ino
        with patch.object(manage, 'systemctl', side_effect=services):
            with self.assertRaises(subprocess.CalledProcessError):
                manage.rollback(backup, start=True)
        self.assertEqual(services.active, current_active)
        self.assertEqual(target.stat().st_ino, inode)

    def test_partial_explicit_rollback_restores_current_version_and_allows_retry(self):
        first = self.root/'data/wled-control/control.py'
        second = self.root/'data/wled-control/equalizer.py'
        v1 = {first:(b'first v1',0o644), second:(b'second v1',0o644)}
        v2 = {first:(b'first v2',0o644), second:(b'second v2',0o644)}
        with patch.object(manage, 'payloads', return_value=v1):
            manage.install(start=False)
        with patch.object(manage, 'payloads', return_value=v2):
            backup = manage.install(start=False)
            current = manage.read_manifest()
            original_write = manage.atomic_write
            failed = []
            def write(path, *args, **kwargs):
                if Path(path) == second and not failed:
                    failed.append(True)
                    raise OSError('injected rollback write failure')
                return original_write(path, *args, **kwargs)
            with patch.object(manage, 'atomic_write', side_effect=write):
                with self.assertRaises(OSError):
                    manage.rollback(backup, start=False)
            self.assertEqual(first.read_bytes(), b'first v2')
            self.assertEqual(second.read_bytes(), b'second v2')
            self.assertEqual(manage.read_manifest(), current)
            manage.check_owned(current, v2)
            manage.rollback(backup, start=False)
            self.assertEqual(first.read_bytes(), b'first v1')
            self.assertEqual(second.read_bytes(), b'second v1')
