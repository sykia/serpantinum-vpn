"""Explicit user actions only. Installation and status probes never call selection."""
import configparser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent

def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

common = load('vpn-common')
bridge = load('vpn-bridge')

def select(subscription_id, server_id):
    locations = load('vpn-locations').load_locations()
    row = next((r for r in locations if r['subscriptionId'] == subscription_id and r['id'] == server_id), None)
    if row is None: raise RuntimeError('Сервер больше не существует. Обновите список.')
    config = configparser.RawConfigParser(strict=False); config.optionxform = str
    config.read(common.happ_config())
    if (config.get('Preferences', 'lastSubscription', fallback='') == subscription_id and
        config.get('Preferences', 'lastServer', fallback='') == server_id):
        return {'ok': True, 'unchanged': True}
    # Only read the database. Let the running Happ process own all writes and switching.
    return bridge.request({'action': 'select', 'subscriptionId': int(subscription_id), 'serverId': int(server_id)})

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'open'
    try:
        if action == 'select' and len(sys.argv) == 4:
            result = select(sys.argv[2], sys.argv[3])
            print(json.dumps(result, ensure_ascii=False)); return
        if action not in ('open', 'connect', 'disconnect'):
            raise RuntimeError('Expected open, connect, disconnect, or select SUB_ID SERVER_ID')
        args = [common.executable('happ')]
        if action != 'open': args.append('happ://' + action)
        result = subprocess.run(args, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(json.dumps({'ok': result.returncode == 0, 'error': '' if result.returncode == 0 else 'Happ отклонил команду'}))
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__': main()
