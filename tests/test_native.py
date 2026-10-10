import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

class NativeBridgeTests(unittest.TestCase):
    def test_no_selection_until_explicit_request(self):
        binary = os.environ.get('HAPP_BRIDGE_TEST_BINARY')
        library = os.environ.get('HAPP_BRIDGE_TEST_LIBRARY')
        if not binary or not library: self.skipTest('Build the native fixture first')
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'calls'
            env = dict(os.environ, XDG_RUNTIME_DIR=tmp, BRIDGE_TEST_LOG=str(log), LD_PRELOAD=library)
            process = subprocess.Popen([binary], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                path = Path(tmp) / 'serpantinum-vpn-happ.sock'
                deadline = time.monotonic() + 5
                while not path.exists() and time.monotonic() < deadline and process.poll() is None: time.sleep(.02)
                self.assertTrue(path.exists(), 'Native adapter did not register')
                def request(payload):
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(2); client.connect(str(path))
                        client.sendall(json.dumps(payload).encode() + b'\n')
                        response = b''
                        while b'\n' not in response: response += client.recv(2048)
                        return json.loads(response)
                self.assertTrue(request({'action':'status'})['ok'])
                self.assertFalse(log.exists())
                self.assertFalse(request({'action':'disconnect'})['ok'])
                self.assertFalse(request({'action':'select','subscriptionId':1.5,'serverId':2})['ok'])
                self.assertFalse(log.exists())
                self.assertTrue(request({'action':'select','subscriptionId':7,'serverId':-9})['ok'])
                self.assertEqual(log.read_text(), '7:-9\n')
            finally:
                process.terminate(); process.communicate(timeout=5)

if __name__ == '__main__': unittest.main()
