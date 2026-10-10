#!/usr/bin/env python3
"""Start Happ at login; load the optional adapter only with matching Qt libraries."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', PACKAGE / 'tools/install.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
spec = importlib.util.spec_from_file_location('autostart', PACKAGE / 'overlay/scripts/vpn-autostart.py')
autostart = importlib.util.module_from_spec(spec); spec.loader.exec_module(autostart)

def qt_core(binary):
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, timeout=10)
    match = re.search(r'libQt6Core\.so\.6\s+=>\s+(\S+)', result.stdout)
    return str(Path(match[1]).resolve()) if result.returncode == 0 and match else None

def main():
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    settings = json.loads((config / 'serpantinum-vpn/runtime.json').read_text())
    command = Path(settings['happ'])
    # The system's active package takes precedence over saved Nix paths.
    current = Path('/run/current-system/sw/bin/happ')
    if current.exists(): command = current.resolve()
    try: binary = installer.detect_happ_binary(command)
    except RuntimeError: binary = None
    if autostart.happ_running(str(binary or settings.get('happ_binary', ''))):
        return
    autostart.prepare_preferences()
    prefixes, values, entry = installer.wrapper_info(command)
    env = dict(os.environ)
    for name, separator, value in prefixes: env[name] = value + separator + env.get(name, '')
    env.update(values)
    bridge = PACKAGE / 'native/libserpantinum-vpn-happ.so'
    try:
        core = qt_core(binary) if binary else None
        if bridge.exists() and core and core == qt_core(bridge):
            env['LD_PRELOAD'] = str(bridge) + (':' + env['LD_PRELOAD'] if env.get('LD_PRELOAD') else '')
        elif bridge.exists(): print('VPN server adapter skipped: Qt runtime changed; rebuild adapter.', file=sys.stderr)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print('VPN server adapter skipped: runtime check failed.', file=sys.stderr)
    os.execve(entry, [str(entry), '--autostart'], env)

if __name__ == '__main__': main()
