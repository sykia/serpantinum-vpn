"""Local runtime paths. No subscription credentials are exported."""
import json
import os
from pathlib import Path
import shutil

CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
CACHE_HOME = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))

def settings():
    try:
        return json.loads((CONFIG_HOME / 'serpantinum-vpn/runtime.json').read_text())
    except (OSError, ValueError):
        return {}

def executable(name):
    configured = settings().get(name)
    if configured and Path(configured).is_file():
        return configured
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f'Missing executable: {name}')
    return resolved

def happ_config():
    return Path(os.environ.get('HAPP_CONFIG', settings().get('happ_config', str(CONFIG_HOME / 'Happ.conf'))))

def happ_database():
    return Path(os.environ.get('HAPP_DATABASE', settings().get('happ_database', str(CONFIG_HOME / 'Happ/subs.db'))))
