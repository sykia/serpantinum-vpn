import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', REPO / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
spec = importlib.util.spec_from_file_location('autostart', REPO / 'overlay/scripts/vpn-autostart.py')
autostart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autostart)

class InstallerTests(unittest.TestCase):
    def test_preferences_keep_current_location_and_other_sections(self):
        text = '[General]\nbld=private-local-value\n[Preferences]\nlastServer=7\nSubscriptions\\subsConnectOnOpen=false\n[Other]\nkeep=yes\n'
        result = autostart.prepare(text)
        self.assertEqual(autostart.prepare(result), result)
        self.assertIn('lastServer=7', result)
        self.assertIn('[Other]\nkeep=yes', result)
        self.assertEqual(result.count('Subscriptions\\subsConnectOnOpen=true'), 1)
        self.assertEqual(result.count('[Preferences]'), 1)

    def test_nested_modules_do_not_duplicate_and_removal_keeps_other_edits(self):
        settings = {'bar': {'modules': {'right': [['wifi', 'vpn'], 'vol']}}}
        self.assertFalse(installer.add_module(settings))
        installer.remove_module(settings)
        self.assertEqual(settings['bar']['modules']['right'], [['wifi'], 'vol'])

    def test_transaction_restores_symlink_and_execute_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); original = root / 'original'; original.write_text('old')
            file = root / 'launcher'; file.symlink_to(original)
            tx = installer.Transaction(root / 'backup')
            tx.write(file, 'new', 0o755)
            self.assertFalse(file.is_symlink())
            self.assertTrue(os.access(file, os.X_OK))
            tx.rollback()
            self.assertTrue(file.is_symlink())
            self.assertEqual(file.read_text(), 'old')

    def test_nix_metadata_is_read_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'wrapper'
            p.write_bytes(b"\x7fELF makeCWrapper '/package/.daemon-wrapped' --prefix 'PATH' ':' '/package/bin' --set 'SERPANTINUM_DIR' '/package/share' $(touch /should-not-exist)")
            prefixes, values, entry = installer.wrapper_info(p)
            self.assertEqual(entry, Path('/package/.daemon-wrapped'))
            self.assertEqual(values['SERPANTINUM_DIR'], '/package/share')
            self.assertEqual(prefixes, [('PATH', ':', '/package/bin')])

    def test_reject_mismatched_source_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'Файлы не изменены'):
                installer.validate_source(Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_install_uninstall_in_isolated_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); source = home / 'upstream'; bindir = home / 'bin'
            bindir.mkdir(); (source / 'assets').mkdir(parents=True)
            (source / 'scripts').mkdir(); (source / 'quickshell').mkdir()
            (source / 'scripts/caching.sh').write_text('#!/bin/bash\n')
            (source / 'scripts/caching.sh').chmod(0o755)
            (source / 'quickshell/Shell.qml').write_text('import QtQuick\nItem {}\n')
            # Read the exact base fixture from an optional checkout supplied by CI/local testing.
            baseline = os.environ.get('SERPANTINUM_TEST_SOURCE')
            if not baseline:
                self.skipTest('Set SERPANTINUM_TEST_SOURCE to the pinned upstream src directory')
            for name in installer.COMPAT['base_files']:
                path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((Path(baseline) / name).read_bytes())
            source.chmod(0o555)
            for name in ['serpantinumd', 'serpantinum', 'happ', 'quickshell', 'node', 'nix-store']:
                file = bindir / name
                file.write_text('#!/usr/bin/env bash\nprintf \'{"compatible":true}\'\n')
                file.chmod(0o755)
            binary = home / 'Happ'; header = bytearray(64)
            header[:6] = b'\x7fELF\x02\x01'; header[18:20] = (62).to_bytes(2, 'little')
            binary.write_bytes(header + bytes(1_000_001))
            config = home / '.config/serpantinum/settings.json'
            config.parent.mkdir(parents=True); config.write_text('{"bar":{"modules":{"right":["wifi"]}},"personal":"keep"}')
            env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                       XDG_DATA_HOME=str(home / '.local/share'), XDG_STATE_HOME=str(home / '.local/state'),
                       PATH=str(bindir) + ':' + os.environ.get('PATH', ''))
            command = [sys.executable, str(REPO / 'tools/install.py'), '--source', str(source),
                       '--happ-binary', str(binary), '--no-systemd']
            subprocess.run(command + ['--dry-run'], env=env, check=True, capture_output=True)
            self.assertFalse((home / '.local/state').exists())
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            target = home / '.local/share/serpantinum-vpn-addon'
            self.assertTrue(os.access(target / 'scripts/caching.sh', os.X_OK))
            self.assertTrue((target / 'quickshell/vpn/VpnPopup.qml').exists())
            self.assertTrue((target / 'addon-package/tools/runtime.py').exists())
            upgraded = subprocess.run([sys.executable, str(REPO / 'tools/install.py'), '--upgrade'], env=env, capture_output=True, text=True)
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            self.assertTrue(list(target.glob('addon-package-backup-*')))
            settings = json.loads(config.read_text()); settings['personal'] = 'changed-after-install'
            config.write_text(json.dumps(settings))
            subprocess.run([sys.executable, str(REPO / 'tools/install.py'), '--uninstall'], env=env, check=True, capture_output=True)
            settings = json.loads(config.read_text())
            self.assertEqual(settings['personal'], 'changed-after-install')
            self.assertEqual(settings['bar']['modules']['right'], ['wifi'])
            self.assertFalse((home / '.local/bin/serpantinum-vpn-start').exists())
            self.assertTrue(target.exists())
            # Exercise service generation using a fake systemctl, never the live session.
            controller = bindir / 'systemctl'
            controller.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/systemctl.log"\ncase "$2" in cat) exit 1;; is-enabled) echo disabled; exit 1;; esac\n')
            controller.chmod(0o755)
            command = command[:-1] + ['--target', str(home / 'systemd-snapshot'), '--state-dir', str(home / 'systemd-state')]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            dropin = home / '.config/systemd/user/serpantinum.service.d/zz-vpn-addon.conf'
            self.assertIn('ExecStart=', dropin.read_text())
            self.assertTrue((home / '.config/systemd/user/happ.service').exists())
            subprocess.run([sys.executable, str(REPO / 'tools/install.py'), '--uninstall', '--state-dir', str(home / 'systemd-state')], env=env, check=True, capture_output=True)
            calls = (home / 'systemctl.log').read_text()
            for forbidden in ['--now', ' restart ', ' stop ', ' start ']:
                self.assertNotIn(forbidden, calls)
            self.assertIn('--user disable happ.service', calls)
            self.assertFalse(dropin.exists())

if __name__ == '__main__':
    unittest.main()
