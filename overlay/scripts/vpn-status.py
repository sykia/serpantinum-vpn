import configparser
import json
import importlib.util
from pathlib import Path

config = configparser.RawConfigParser(strict=False)
config.optionxform = str
spec = importlib.util.spec_from_file_location('vpn_common', Path(__file__).with_name('vpn-common.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
config.read(common.happ_config())
location = config.get('Preferences', 'lastServerName', fallback='Happ')
connected = False
for process in Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        executable = (process / 'cmdline').read_bytes().split(b'\0', 1)[0].decode(errors='replace')
        if executable == common.settings().get('happ_core') or '/happ/bin/core/xray' in executable or '/Happ/bin/core/xray' in executable:
            connected = True
            break
    except OSError:
        pass
print(json.dumps({'connected': connected, 'location': location,
    'serverId': config.get('Preferences', 'lastServer', fallback='')}, ensure_ascii=False))
