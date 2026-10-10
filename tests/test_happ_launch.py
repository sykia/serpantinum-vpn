import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('happ_launch', REPO / 'tools/happ-launch.py')
launch = importlib.util.module_from_spec(spec); spec.loader.exec_module(launch)

class HappLaunchTests(unittest.TestCase):
    def test_running_client_is_not_started_or_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp); (config/'serpantinum-vpn').mkdir()
            (config/'serpantinum-vpn/runtime.json').write_text(json.dumps({'happ':'/fake/happ','happ_binary':'/fake/Happ'}))
            with patch.dict(os.environ, XDG_CONFIG_HOME=tmp), patch.object(launch.installer,'detect_happ_binary',return_value=Path('/fake/Happ')), patch.object(launch.autostart,'happ_running',return_value=True), patch.object(launch.autostart,'prepare_preferences') as prepare, patch.object(launch.os,'execve') as execute:
                launch.main()
                prepare.assert_not_called(); execute.assert_not_called()

    def test_missing_native_or_qt_does_not_prevent_client_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp); (config/'serpantinum-vpn').mkdir()
            (config/'serpantinum-vpn/runtime.json').write_text(json.dumps({'happ':'/fake/happ'}))
            with patch.dict(os.environ, XDG_CONFIG_HOME=tmp), patch.object(launch.installer,'detect_happ_binary',side_effect=RuntimeError('unsupported future version')), patch.object(launch.installer,'wrapper_info',return_value=([],{},Path('/fake/Happ'))), patch.object(launch.autostart,'happ_running',return_value=False), patch.object(launch.autostart,'prepare_preferences') as prepare, patch.object(launch.os,'execve') as execute:
                launch.main()
                prepare.assert_called_once()
                self.assertEqual(execute.call_args.args[0], Path('/fake/Happ'))
                self.assertEqual(execute.call_args.args[1], ['/fake/Happ','--autostart'])
