"""Only explicit user actions call this script. Installation never calls it."""
import importlib.util
from pathlib import Path
import subprocess
import sys

spec = importlib.util.spec_from_file_location('vpn_common', Path(__file__).with_name('vpn-common.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'open'
    if action not in ('open', 'connect', 'disconnect'):
        raise SystemExit('Expected open, connect, or disconnect')
    args = [common.executable('happ')]
    if action != 'open':
        args.append('happ://' + action)
    raise SystemExit(subprocess.call(args))

if __name__ == '__main__':
    main()
