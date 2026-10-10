import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import socket
import threading

REPO = Path(__file__).resolve().parents[1]
def module(path, name):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value
runtime = module('tools/runtime.py', 'runtime')
control = module('overlay/scripts/vpn-control.py', 'control')
bridge = module('overlay/scripts/vpn-bridge.py', 'bridge')

class RuntimeTests(unittest.TestCase):
    def test_shell_children_find_addon_cli_and_keep_system_dependencies(self):
        with patch.object(runtime.installer, 'wrapper_info', return_value=([('PATH', ':', '/system/dependencies')], {}, Path('/system/daemon'))), patch.object(runtime.os, 'execve') as execute:
            runtime.execute(Path('/system/wrapper'), Path('/addon/shell'), ['start'])
        environment = execute.call_args.args[2]
        self.assertTrue(environment['PATH'].startswith(str(runtime.HOME / '.local/bin') + ':'))
        self.assertIn('/system/dependencies', environment['PATH'])
        self.assertEqual(environment['MAIN_QML'], '/addon/shell/quickshell/Shell.qml')

    def test_overlay_preserves_upstream_changes_and_rejects_missing_anchor(self):
        baseline = os.environ.get('SERPANTINUM_TEST_SOURCE')
        if not baseline: self.skipTest('Set SERPANTINUM_TEST_SOURCE')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; target = root / 'target'
            for name in json.loads((REPO / 'patches.json').read_text()):
                for directory in [source, target]:
                    file = directory / name; file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text('// New upstream feature\n' + (Path(baseline) / name).read_text())
            runtime.apply_overlay(source, target)
            for name in json.loads((REPO / 'patches.json').read_text()):
                self.assertTrue((target / name).read_text().startswith('// New upstream feature'))
                self.assertIn('vpn', (target / name).read_text())
            (source / 'quickshell/WindowRegistry.js').write_text('incompatible')
            with self.assertRaises(RuntimeError): runtime.apply_overlay(source, target)

    def test_bridge_status_is_read_only_and_missing_bridge_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, XDG_RUNTIME_DIR=tmp):
            with self.assertRaises(bridge.BridgeError): bridge.request({'action':'status'})
            server = socket.socket(socket.AF_UNIX); server.bind(tmp + '/serpantinum-vpn-happ.sock'); server.listen()
            received = []
            def respond():
                conn, _ = server.accept()
                with conn:
                    received.append(json.loads(conn.recv(2048)))
                    conn.sendall(b'{"ok":true}\n')
            worker = threading.Thread(target=respond); worker.start()
            self.assertTrue(bridge.request({'action':'status'})['ok'])
            worker.join(); server.close()
            self.assertEqual(received, [{'action':'status'}])

    def test_invalid_server_never_sends_command(self):
        class Locations:
            @staticmethod
            def load_locations(): return []
        with patch.object(control, 'load', return_value=Locations), patch.object(control.bridge, 'request') as request:
            with self.assertRaises(RuntimeError): control.select('1','2')
            request.assert_not_called()

    def test_current_selection_never_switches(self):
        class Locations:
            @staticmethod
            def load_locations(): return [{'subscriptionId':'1', 'id':'2'}]
        with tempfile.TemporaryDirectory() as tmp:
            conf=Path(tmp)/'Happ.conf'; conf.write_text('[Preferences]\nlastSubscription=1\nlastServer=2\n')
            with patch.object(control, 'load', return_value=Locations), patch.object(control.common, 'happ_config', return_value=conf), patch.object(control.bridge, 'request') as request:
                self.assertTrue(control.select('1','2')['unchanged'])
                request.assert_not_called()

    def test_selection_uses_ids_from_database(self):
        class Locations:
            @staticmethod
            def load_locations(): return [{'subscriptionId':'1', 'id':'3'}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(control, 'load', return_value=Locations), patch.object(control.common, 'happ_config', return_value=Path(tmp)/'Happ.conf'), patch.object(control.bridge, 'request', return_value={'ok':True}) as request:
            self.assertTrue(control.select('1','3')['ok'])
            request.assert_called_once_with({'action':'select','subscriptionId':1,'serverId':3})
