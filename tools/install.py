#!/usr/bin/env python3
"""Install a checked overlay into a private snapshot. Never stop running services."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
COMPAT = json.loads((REPO / 'compatibility.json').read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(content.encode() if isinstance(content, str) else content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def resolve_command(value):
    result = shutil.which(str(value))
    if not result:
        raise RuntimeError(f'Не найдена команда: {value}')
    return Path(result).resolve()

def wrapper_info(binary):
    """Read Nix wrapper metadata without executing or evaluating shell text."""
    text = binary.read_bytes().decode(errors='replace')
    prefixes = re.findall(r"--prefix '([A-Z0-9_]+)' '([^']*)' '([^']*)'", text)
    sets = re.findall(r"--set '([A-Z0-9_]+)' '([^']*)'", text)
    original = re.search(r"makeCWrapper '([^']+)'", text)
    return prefixes, dict(sets), Path(original[1]) if original else binary

def detect_source(daemon):
    _, env, _ = wrapper_info(daemon)
    candidates = [env.get('SERPANTINUM_DIR'), os.environ.get('SERPANTINUM_DIR'),
                  daemon.parent.parent / 'src', daemon.parent.parent / 'share/serpantinum',
                  Path.home() / '.local/share/serpantinum/src',
                  Path.home() / '.local/share/serpantinum', Path('/usr/share/serpantinum')]
    for candidate in candidates:
        if candidate and (Path(candidate) / 'quickshell/Shell.qml').is_file():
            return Path(candidate).resolve()
    raise RuntimeError('Не найден каталог Serpantinum. Укажите --source /path/to/serpantinum/src')

def validate_source(source):
    for name, expected in COMPAT['base_files'].items():
        file = source / name
        if not file.is_file() or digest(file) != expected:
            raise RuntimeError(f'Несовместимый или изменённый Serpantinum: {name}. '
                               f'Ожидается {COMPAT["serpantinum_version"]}, revision '
                               f'{COMPAT["serpantinum_revision"]}. Файлы не изменены.')
    for name in ['quickshell/Shell.qml', 'scripts/caching.sh', 'assets']:
        if not (source / name).exists():
            raise RuntimeError(f'Неполный каталог Serpantinum: {name}')

def detect_happ_binary(command, explicit=None):
    if explicit:
        candidates = [Path(explicit)]
    else:
        text = command.read_bytes().decode(errors='replace')
        candidates = [command]
        candidates.extend(Path(p) for p in re.findall(r"(/[a-zA-Z0-9_./+\-]+/Happ)\b", text))
        candidates.extend([command.parent / 'Happ', command.parent / 'bin/Happ',
                           command.parent.parent / 'happ/bin/Happ',
                           Path('/opt/happ/bin/Happ'), Path('/opt/Happ/bin/Happ'),
                           Path('/opt/Happ/Happ'), Path('/usr/lib/happ/bin/Happ'),
                           Path('/usr/share/happ/bin/Happ')])
        # The process belongs to the user; read cmdline only, never attach to it.
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                exe = (process / 'cmdline').read_bytes().split(b'\0')[0].decode()
                if Path(exe).name == 'Happ':
                    candidates.insert(0, Path(exe))
            except (OSError, UnicodeError):
                pass
    for candidate in candidates:
        try:
            with candidate.open('rb') as file:
                header = file.read(64)
            if header[:6] == b'\x7fELF\x02\x01' and int.from_bytes(header[18:20], 'little') == 62:
                # Wrapper ELF executables are much smaller than the actual Qt app.
                if candidate.stat().st_size > 1_000_000:
                    return candidate.resolve()
        except OSError:
            pass
    raise RuntimeError('Не найден ELF Happ x86_64. Укажите --happ-binary /path/to/Happ')

def locate_dependency(name, prefixes):
    candidate = shutil.which(name)
    if candidate:
        return str(Path(candidate).resolve())
    for variable, separator, value in reversed(prefixes):
        if variable == 'PATH':
            for directory in value.split(separator):
                file = Path(directory) / name
                if file.is_file() and os.access(file, os.X_OK):
                    return str(file.resolve())
    raise RuntimeError(f'Не найден {name}. Установите зависимости из README.')

def launcher(target, command, prefix_lines, python, config_home):
    lines = ['#!/usr/bin/env bash', 'set -euo pipefail']
    for variable, separator, value in prefix_lines:
        lines.append(f'export {variable}={shlex.quote(value + separator)}"${{{variable}:-}}"')
    lines.extend([f'export PATH={shlex.quote(str(Path(python).parent) + ":")}"$PATH"',
                  f'export XDG_CONFIG_HOME={shlex.quote(str(config_home))}',
                  f'export SERPANTINUM_DIR={shlex.quote(str(target))}',
                  'export SERPANTINUM_VERSION=2.2.5-1-vpn',
                  f'exec {shlex.quote(str(command))} "$@"'])
    return '\n'.join(lines) + '\n'

def add_module(settings):
    def contains(value):
        if isinstance(value, str):
            return value == 'vpn'
        if isinstance(value, dict):
            return value.get('id') == 'vpn' or value.get('type') == 'vpn'
        if isinstance(value, list):
            return any(contains(item) for item in value)
        return False
    modules = settings.setdefault('bar', {}).setdefault('modules', {})
    if not isinstance(modules, dict):
        raise RuntimeError('Неизвестный формат bar.modules')
    if any(contains(value) for value in modules.values()):
        return False
    right = modules.setdefault('right', [])
    if not isinstance(right, list):
        raise RuntimeError('bar.modules.right должен быть массивом')
    right.append('vpn')
    return True

def remove_module(settings):
    def clean(value):
        if not isinstance(value, list):
            return value
        return [clean(item) for item in value if item != 'vpn' and
                not (isinstance(item, dict) and (item.get('id') == 'vpn' or item.get('type') == 'vpn'))]
    modules = settings.get('bar', {}).get('modules', {})
    for key, value in modules.items():
        modules[key] = clean(value)

class Transaction:
    def __init__(self, backup):
        self.backup = backup
        self.records = []

    def write(self, path, content, mode=0o600):
        index = len(self.records)
        record = {'path': str(path), 'backup': None}
        if path.exists() or path.is_symlink():
            saved = self.backup / str(index)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved, follow_symlinks=False)
            record['backup'] = str(saved)
        self.records.append(record)
        atomic_write(path, content, mode)
        record['installed_hash'] = digest(path)

    def rollback(self):
        for record in reversed(self.records):
            path = Path(record['path'])
            if record['backup']:
                path.unlink(missing_ok=True)
                shutil.copy2(record['backup'], path, follow_symlinks=False)
            else:
                path.unlink(missing_ok=True)

def service_escape(value):
    # systemd specifiers and C-style quoted command paths.
    return str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')

def pin_nix(path, root):
    parts = path.parts
    if len(parts) > 3 and parts[1:3] == ('nix', 'store'):
        package = Path('/nix/store') / parts[3]
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['nix-store', '--add-root', str(root), '--indirect', '--realise', str(package)],
                       check=True, stdout=subprocess.DEVNULL)
        return str(root)
    return None

def install(args, paths):
    target, state, config, bin_dir = paths
    manifest = state / 'installation.json'
    if manifest.exists():
        raise RuntimeError('Уже установлено. Для обновления используйте --upgrade.')
    if target.exists():
        raise RuntimeError(f'{target} уже существует без manifest этого установщика. '
                           'Каталог не изменён. Укажите новый каталог через --target.')
    daemon = resolve_command(args.daemon)
    source = Path(args.source).expanduser().resolve() if args.source else detect_source(daemon)
    # Validate integration anchors without overwriting any upstream file.
    for name, changes in json.loads((REPO / 'patches.json').read_text()).items():
        content = (source / name).read_text()
        for change in changes:
            if content.count(change['old']) != 1:
                raise RuntimeError('Несовместимый Serpantinum: ' + name)
    prefixes, _, daemon_entry = wrapper_info(daemon)
    python = sys.executable
    node = locate_dependency('node', prefixes)
    bash = locate_dependency('bash', prefixes)
    locate_dependency('quickshell', prefixes)
    happ = resolve_command(args.happ)
    happ_binary = detect_happ_binary(happ, args.happ_binary)
    checked = subprocess.run([node, str(REPO / 'overlay/scripts/happ-read.cjs'),
                              str(happ_binary), '--check-binary'], capture_output=True, timeout=10)
    if checked.returncode:
        raise RuntimeError('Несовместимый Happ. Для этого релиза нужен адаптер базы Happ 4.4.8 x86_64.')
    cli = resolve_command(args.cli)
    cli_prefixes, _, cli_entry = wrapper_info(cli)
    settings_file = config / 'serpantinum/settings.json'
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    added = add_module(settings)
    if not args.no_systemd and not shutil.which('systemctl'):
        raise RuntimeError('Нужны пользовательские службы systemd. Для ручного запуска используйте --no-systemd.')
    print(f'Источник: {source}\nКопия: {target}\nHapp ELF: {happ_binary}')
    print('VPN и работающие службы не будут остановлены или перезапущены.')
    if args.dry_run:
        print('Предварительная проверка пройдена. Файлы не изменены.')
        return
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = state / 'backup'
    if backup.exists():
        raise RuntimeError(f'Уже есть резервная копия: {backup}. Сохраните её или выберите другой --state-dir.')
    tx = Transaction(backup)
    roots = []
    enabled_before = {}
    stage = None
    published = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.serpantinum-vpn-', dir=target.parent))
        shutil.copytree(source, stage, dirs_exist_ok=True)
        stage.chmod(stage.stat().st_mode | 0o200)
        # Nix store modes are read-only. Retain execute bits while making the copy editable.
        for file in stage.rglob('*'):
            if not file.is_symlink():
                os.chmod(file, stat.S_IMODE(file.stat().st_mode) | stat.S_IWUSR)
        spec = importlib.util.spec_from_file_location('runtime', REPO / 'tools/runtime.py')
        runtime_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime_module)
        runtime_module.apply_overlay(source, stage)
        package = stage / 'addon-package'
        for name in ['tools', 'overlay', 'native']:
            shutil.copytree(REPO / name, package / name, ignore=shutil.ignore_patterns('__pycache__', '*.so'))
        for name in ['patches.json', 'compatibility.json', 'VERSION']:
            shutil.copy2(REPO / name, package / name)
        (package / 'commands.json').write_text(json.dumps({'daemon': args.daemon, 'cli': args.cli, 'source': args.source}))
        if args.happ_bridge:
            shutil.copy2(args.happ_bridge, package / 'native/libserpantinum-vpn-happ.so')
        (stage / 'vpn-addon-version').write_text((REPO / 'VERSION').read_text())
        stage.rename(target)
        published = True
        for pinned, name in [(daemon, 'serpantinum'), (happ_binary, 'happ'), (Path(node), 'node'), (Path(python), 'python')]:
            root = pin_nix(pinned, state / 'roots' / name)
            if root:
                roots.append(root)
        if args.happ_bridge:
            linked = subprocess.run(['ldd', str(args.happ_bridge)], capture_output=True, text=True, check=True)
            packages = {Path(p) for p in re.findall(r'(/nix/store/[^/\s]+)', linked.stdout)}
            for index, package in enumerate(sorted(packages)):
                root = pin_nix(package, state / 'roots' / ('bridge-' + str(index)))
                if root: roots.append(root)
        runtime = {'happ': str(happ), 'happ_binary': str(happ_binary), 'node': node,
                   'happ_core': str(happ_binary.parent / 'core/xray')}
        if args.happ_config:
            runtime['happ_config'] = str(Path(args.happ_config).expanduser().resolve())
        if args.happ_database:
            runtime['happ_database'] = str(Path(args.happ_database).expanduser().resolve())
        tx.write(config / 'serpantinum-vpn/runtime.json', json.dumps(runtime, indent=2) + '\n')
        start = bin_dir / 'serpantinum-vpn-start'
        runtime_entry = target / 'addon-package/tools/runtime.py'
        launch_env = '#!/usr/bin/env bash\nexport XDG_CONFIG_HOME=' + shlex.quote(str(config)) + '\nexport SERPANTINUM_VPN_STATE_DIR=' + shlex.quote(str(state)) + '\n'
        command = launch_env + 'exec ' + shlex.quote(python) + ' ' + shlex.quote(str(runtime_entry)) + ' start\n'
        tx.write(start, command, 0o755)
        cli_script = launch_env + 'exec ' + shlex.quote(python) + ' ' + shlex.quote(str(runtime_entry)) + ' cli "$@"\n'
        tx.write(bin_dir / 'serpantinum-vpn', cli_script, 0o755)
        tx.write(bin_dir / 'serpantinum', cli_script, 0o755)
        tx.write(state / 'active.json', json.dumps({'target': str(target)}))
        tx.write(settings_file, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')
        if not args.no_systemd:
            dropin = config / 'systemd/user/serpantinum.service.d/zz-vpn-addon.conf'
            tx.write(dropin, '[Service]\nExecStart=\nExecStart="' + service_escape(bash) + '" "' + service_escape(start) + '"\n')
            if subprocess.run(['systemctl', '--user', 'cat', 'serpantinum.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                unit = '[Unit]\nDescription=Serpantinum with VPN addon\nPartOf=graphical-session.target\nAfter=graphical-session.target\n\n[Service]\nType=simple\nExecStart="' + service_escape(bash) + '" "' + service_escape(start) + '"\nRestart=on-failure\n\n[Install]\nWantedBy=graphical-session.target\n'
                tx.write(config / 'systemd/user/serpantinum.service', unit)
            if not args.no_happ_autostart:
                auto = bin_dir / 'serpantinum-vpn-happ-autostart'
                auto_script = '#!/usr/bin/env bash\nset -euo pipefail\nexport XDG_CONFIG_HOME=' + shlex.quote(str(config)) + '\nexec ' + shlex.quote(python) + ' ' + shlex.quote(str(target / 'addon-package/tools/happ-launch.py')) + '\n'
                tx.write(auto, auto_script, 0o755)
                tx.write(config / 'systemd/user/happ.service.d/zz-vpn-addon.conf', '[Service]\nExecStart=\nExecStart="' + service_escape(bash) + '" "' + service_escape(auto) + '"\n')
                if subprocess.run(['systemctl', '--user', 'cat', 'happ.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
                    tx.write(config / 'systemd/user/happ.service', '[Unit]\nDescription=Happ auto-connect\nPartOf=graphical-session.target\nAfter=graphical-session.target\n\n[Service]\nExecStart="' + service_escape(bash) + '" "' + service_escape(auto) + '"\n\n[Install]\nWantedBy=graphical-session.target\n')
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            # Enable for future logins only. Never use --now.
            services = ['serpantinum.service'] + ([] if args.no_happ_autostart else ['happ.service'])
            for service in services:
                before = subprocess.run(['systemctl', '--user', 'is-enabled', service], capture_output=True, text=True)
                enabled_before[service] = before.stdout.strip()
                if enabled_before[service] not in ('enabled', 'enabled-runtime'):
                    subprocess.run(['systemctl', '--user', 'enable', service], check=True)
        atomic_write(manifest, json.dumps({'target': str(target), 'source': str(source),
                     'files': tx.records, 'roots': roots, 'settings_file': str(settings_file),
                     'added_module': added, 'systemd': not args.no_systemd,
                     'enabled_before': enabled_before}, indent=2) + '\n')
    except Exception:
        for service, before in enabled_before.items():
            if before not in ('enabled', 'enabled-runtime'):
                subprocess.run(['systemctl', '--user', 'disable', service], stderr=subprocess.DEVNULL)
        tx.rollback()
        for root in roots:
            Path(root).unlink(missing_ok=True)
        if published:
            shutil.rmtree(target)
        if not args.no_systemd:
            subprocess.run(['systemctl', '--user', 'daemon-reload'], stderr=subprocess.DEVNULL)
        raise
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)
    print('Установлено. Дополнение загрузится при следующем графическом входе. VPN не перезапускался.')
    print(f'Ручной запуск: {start}\nУдаление: bash install.sh --uninstall --state-dir {shlex.quote(str(state))}')

def uninstall(args, paths):
    _, state, _, _ = paths
    file = state / 'installation.json'
    if not file.exists():
        raise RuntimeError('Manifest установки не найден. Ничего не изменено.')
    info = json.loads(file.read_text())
    changed = [record['path'] for record in info['files'] if Path(record['path']).exists()
               and digest(Path(record['path'])) != record.get('installed_hash')
               and record['path'] != info['settings_file'] and Path(record['path']).name != 'active.json']
    if changed:
        raise RuntimeError('Файлы изменены после установки; сначала сохраните свои изменения: ' + ', '.join(changed))
    if args.dry_run:
        print('Проверка удаления пройдена. Файлы не изменены.')
        return
    for service, before in info.get('enabled_before', {}).items():
        if before not in ('enabled', 'enabled-runtime'):
            subprocess.run(['systemctl', '--user', 'disable', service], check=True)
    for record in reversed(info['files']):
        path = Path(record['path'])
        if str(path) == info['settings_file']:
            if info['added_module'] and path.exists():
                settings = json.loads(path.read_text())
                remove_module(settings)
                atomic_write(path, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')
            continue
        path.unlink(missing_ok=True)
        if record['backup']:
            shutil.copy2(record['backup'], path, follow_symlinks=False)
    # Keep the snapshot and backup: the running shell may still use them.
    for root in info['roots']:
        Path(root).unlink(missing_ok=True)
    if info['systemd']:
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    file.rename(state / 'uninstalled.json')
    print('Переопределения запуска и запись VPN удалены. Оригинальная оболочка загрузится при следующем входе.')
    print(f'Копия и резервные файлы сохранены в {info["target"]} и {state}. VPN-процессы не останавливались.')

def upgrade(args, paths):
    _, state, _, _ = paths
    manifest = json.loads((state / 'installation.json').read_text())
    target = Path(manifest['target'])
    package = target / 'addon-package'
    if args.dry_run:
        print('Обновится только пакет дополнения. Happ и оболочка не перезапускаются.')
        return
    with (state / 'install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage = Path(tempfile.mkdtemp(prefix='.upgrade-', dir=target))
        try:
            for name in ['tools', 'overlay', 'native']:
                shutil.copytree(REPO / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.so'))
            for name in ['patches.json', 'compatibility.json', 'VERSION']:
                shutil.copy2(REPO / name, stage / name)
            if (package / 'commands.json').exists(): shutil.copy2(package / 'commands.json', stage / 'commands.json')
            bridge = args.happ_bridge or package / 'native/libserpantinum-vpn-happ.so'
            if bridge.exists(): shutil.copy2(bridge, stage / 'native/libserpantinum-vpn-happ.so')
            saved = target / ('addon-package-backup-' + os.urandom(6).hex())
            package.rename(saved)
            try: stage.rename(package)
            except Exception:
                saved.rename(package)
                raise
        finally:
            if stage.exists(): shutil.rmtree(stage)
    print('Пакет дополнения обновлён. Загрузится при следующем запуске оболочки. VPN не изменён.')

def main():
    parser = argparse.ArgumentParser(description="Установка VPN-дополнения в отдельную копию Serpantinum с проверками и откатом.")
    parser.add_argument('--source', help='Каталог Serpantinum, содержащий quickshell/')
    parser.add_argument('--daemon', default='serpantinumd')
    parser.add_argument('--cli', default='serpantinum')
    parser.add_argument('--happ', default='happ')
    parser.add_argument('--happ-binary', help='Сам ELF-файл Happ 4.4.8 x86_64, а не wrapper')
    parser.add_argument('--happ-config')
    parser.add_argument('--happ-bridge', type=Path, help='Собранный native/libserpantinum-vpn-happ.so (Qt должен совпадать с Happ)')
    parser.add_argument('--upgrade', action='store_true', help='Обновить пакет дополнения; действующие службы не перезапускаются')
    parser.add_argument('--happ-database')
    parser.add_argument('--target', type=Path)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-systemd', action='store_true', help='Создать launchers без настройки служб входа')
    parser.add_argument('--no-happ-autostart', action='store_true')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Запускайте своим обычным пользователем, без sudo.')
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')).resolve()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
    state_home = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
    target = (args.target or data / 'serpantinum-vpn-addon').expanduser().resolve()
    state = (args.state_dir or state_home / 'serpantinum-vpn-addon').expanduser().resolve()
    paths = (target, state, config, home / '.local/bin')
    if args.upgrade:
        upgrade(args, paths)
        return
    # A dry run must not create lock/state directories.
    if args.dry_run:
        (uninstall if args.uninstall else install)(args, paths)
        return
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / 'install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (uninstall if args.uninstall else install)(args, paths)

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        sys.exit(1)
