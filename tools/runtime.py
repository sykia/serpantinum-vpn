#!/usr/bin/env python3
"""Compose the addon with the installed shell at launch. Never control Happ here."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import importlib.util

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', PACKAGE / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
HOME = Path.home()
STATE = Path(os.environ.get('SERPANTINUM_VPN_STATE_DIR', str(Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'serpantinum-vpn-addon')))
DATA = Path(os.environ.get('XDG_DATA_HOME', HOME / '.local/share')) / 'serpantinum-vpn-shells'

def system_command(name):
    try: commands = json.loads((PACKAGE / 'commands.json').read_text())
    except (OSError, ValueError): commands = {}
    configured = commands.get('daemon' if name == 'serpantinumd' else 'cli', name)
    if configured != name:
        return installer.resolve_command(configured)
    # Skip our own shims; NixOS always uses the currently active system generation.
    candidates = [Path('/run/current-system/sw/bin') / name]
    candidates += [Path(p) / name for p in os.environ.get('PATH', '').split(os.pathsep)
                   if Path(p).resolve() != (HOME / '.local/bin').resolve()]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK): return path.resolve()
    raise RuntimeError('Missing installed command: ' + name)

def apply_overlay(source, target):
    patches = json.loads((PACKAGE / 'patches.json').read_text())
    for name, changes in patches.items():
        content = (source / name).read_text()
        for change in changes:
            if content.count(change['old']) != 1:
                raise RuntimeError('Upstream integration changed: ' + name)
            content = content.replace(change['old'], change['new'], 1)
        file = target / name
        file.write_text(content)
    for file in (PACKAGE / 'overlay').rglob('*'):
        relative = file.relative_to(PACKAGE / 'overlay')
        if file.is_file() and str(relative) not in patches:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)

def compose(source):
    metadata = ''.join(str(p.relative_to(source)) + ':' + str(p.stat().st_size) + ':' + str(p.stat().st_mtime_ns) for p in sorted(source.rglob('*')) if p.is_file())
    key = hashlib.sha256((str(source) + metadata + (PACKAGE / 'VERSION').read_text() +
        (PACKAGE / 'patches.json').read_text()).encode()).hexdigest()[:20]
    target = DATA / key
    if (target / '.complete').exists(): return target
    DATA.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=DATA))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        stage.chmod(stage.stat().st_mode | 0o200)
        for file in stage.rglob('*'):
            if not file.is_symlink(): file.chmod(file.stat().st_mode | 0o200)
        apply_overlay(source, stage)
        (stage / '.complete').write_text(str(source))
        if target.exists(): shutil.rmtree(stage)
        else: stage.rename(target)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return target

def execute(binary, target, arguments):
    prefixes, values, entry = installer.wrapper_info(binary)
    env = dict(os.environ)
    for key, sep, value in prefixes: env[key] = value + sep + env.get(key, '')
    env.update(values)
    env['SERPANTINUM_DIR'] = str(target)
    # Do not keep MAIN_QML from another shell generation.
    env['MAIN_QML'] = str(target / 'quickshell/Shell.qml')
    env['PATH'] = str(HOME / '.local/bin') + ':' + str(Path(sys.executable).parent) + ':' + env.get('PATH', '')
    os.execve(entry, [str(entry), *arguments], env)

def route_commands():
    hyprctl = shutil.which('hyprctl')
    if not hyprctl or not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'): return
    script = 'local b = os.getenv("HOME") .. "/.local/bin"; local p = os.getenv("PATH") or ""; if not (":" .. p .. ":"):find(":" .. b .. ":", 1, true) then hl.env("PATH", b .. ":" .. p) end'
    try:
        result = subprocess.run([hyprctl, 'eval', script], capture_output=True, text=True, timeout=5)
        if result.returncode or 'unknown' in result.stdout.lower() or "can't" in result.stdout.lower():
            subprocess.run([hyprctl, 'keyword', 'env', 'PATH,' + str(HOME / '.local/bin') + ':' + os.environ.get('PATH', '')], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        print('VPN command routing unavailable; use ~/.local/bin/serpantinum-vpn in compositor bindings.', file=sys.stderr)

def main():
    if sys.argv[1] == 'start':
        route_commands()
        binary = system_command('serpantinumd')
        try: configured_source = json.loads((PACKAGE / 'commands.json').read_text()).get('source')
        except (OSError, ValueError): configured_source = None
        source = Path(configured_source).expanduser().resolve() if configured_source else installer.detect_source(binary)
        try: target = compose(source)
        except (OSError, RuntimeError, ValueError) as error:
            # A future incompatible shell must still start normally.
            print('VPN addon disabled for this shell version: ' + str(error), file=sys.stderr)
            target = source
        installer.atomic_write(STATE / 'active.json', json.dumps({'target':str(target)}))
        execute(binary, target, ['start'])
    else:
        binary = system_command('serpantinum')
        try: target = Path(json.loads((STATE / 'active.json').read_text())['target'])
        except (OSError, ValueError, KeyError): target = installer.detect_source(system_command('serpantinumd'))
        if not (target / 'quickshell/Shell.qml').exists():
            target = installer.detect_source(system_command('serpantinumd'))
        execute(binary, target, sys.argv[2:])

if __name__ == '__main__': main()
