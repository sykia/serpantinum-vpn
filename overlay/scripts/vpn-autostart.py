"""Set Happ login preferences before launching it, never edit a running client."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

spec = importlib.util.spec_from_file_location('vpn_common', Path(__file__).with_name('vpn-common.py'))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
PREFERENCES = {'AdvancedSettings\\startMinimized': 'true',
               'Subscriptions\\subsConnectOnOpen': 'true',
               'Subscriptions\\subsConnectTypeOnOpen': 'lastused'}

def prepare(text):
    lines = text.splitlines()
    result = []
    inside = False
    section_seen = False
    remaining = dict(PREFERENCES)
    for line in lines:
        if line.startswith('['):
            if inside:
                result.extend(key + '=' + val for key, val in remaining.items())
                remaining.clear()
            inside = line.strip() == '[Preferences]'
            section_seen = section_seen or inside
        key = line.split('=', 1)[0]
        if inside and key in PREFERENCES:
            if key in remaining:
                result.append(key + '=' + remaining.pop(key))
            continue
        result.append(line)
    if not section_seen:
        result.extend(['', '[Preferences]'])
    result.extend(key + '=' + val for key, val in remaining.items())
    return '\n'.join(result) + '\n'

def happ_running(binary):
    for process in Path('/proc').iterdir():
        if process.name.isdigit():
            try:
                if (process / 'cmdline').read_bytes().split(b'\0')[0].decode() == binary:
                    return True
            except (OSError, UnicodeError):
                pass
    return False

def prepare_preferences():
    conf = common.happ_config()
    conf.parent.mkdir(parents=True, exist_ok=True)
    backup = conf.with_name(conf.name + '.before-vpn-addon')
    if conf.exists() and not backup.exists():
        shutil.copy2(conf, backup)
        backup.chmod(0o600)
    text = conf.read_text() if conf.exists() else ''
    fd, tmp = tempfile.mkstemp(dir=conf.parent, prefix='.happ-autostart-')
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(prepare(text))
        os.replace(tmp, conf)
    finally:
        Path(tmp).unlink(missing_ok=True)

def main():
    if happ_running(common.settings().get('happ_binary', '')):
        return
    prepare_preferences()
    os.execv(common.executable('happ'), [common.executable('happ'), '--autostart'])

if __name__ == '__main__':
    main()
