"""Read Happ server metadata and measure TCP handshake latency without switching VPN."""
import concurrent.futures
import configparser
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import importlib.util
import tempfile

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('vpn_common', BASE / 'vpn-common.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
CACHE = common.CACHE_HOME / 'serpantinum/vpn/locations.json'

def load_locations():
    binary = common.settings().get('happ_binary')
    if not binary:
        raise RuntimeError('Configure happ_binary with the installer')
    with sqlite3.connect(common.happ_database().resolve().as_uri() + '?mode=ro', uri=True) as connection:
        row = connection.execute('SELECT data,tag FROM subscriptions ORDER BY version DESC LIMIT 1').fetchone()
        if row is None:
            raise RuntimeError('No subscriptions')
        data, tag = row
    if isinstance(data, bytes):
        data = data.decode()
    if isinstance(tag, bytes):
        tag = tag.decode()
    result = subprocess.run([common.executable('node'), str(BASE / 'happ-read.cjs'), binary],
        input=json.dumps({'data': data, 'tag': tag}), text=True, capture_output=True, timeout=10, check=True)
    return json.loads(result.stdout)

def measure(location):
    if not location['host']:
        return None
    try:
        started = time.perf_counter()
        with socket.create_connection((location['host'], location['port']), timeout=3):
            return max(1, round((time.perf_counter() - started) * 1000))
    except OSError:
        return None

def main():
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = {'locations': [], 'updated': 0}
    try:
        locations = load_locations()
    except Exception:
        cached['error'] = 'Список недоступен: нужен совместимый Happ 4.4.8 x86_64 и импортированная подписка. См. README.'
        print(json.dumps(cached, ensure_ascii=False))
        return
    old = {(row['subscriptionId'], row['id'], row.get('guid')): row for row in cached.get('locations', [])}
    for row in locations:
        row['ping'] = old.get((row['subscriptionId'], row['id'], row.get('guid')), {}).get('ping')
        row['tested'] = old.get((row['subscriptionId'], row['id'], row.get('guid')), {}).get('tested', False)
    updated = cached.get('updated', 0)
    if '--ping' in sys.argv:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for row, ping in zip(locations, pool.map(measure, locations)):
                row['ping'] = ping
                row['tested'] = True
        updated = int(time.time())
    result = {'locations': locations, 'updated': updated, 'error': ''}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=CACHE.parent, prefix='.locations-')
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(result, file, ensure_ascii=False)
        temporary.replace(CACHE)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
