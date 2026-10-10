"""Local Happ bridge client. Status queries never change the connection."""
import json
import os
from pathlib import Path
import socket

class BridgeError(RuntimeError): pass

def request(payload):
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise BridgeError('Нет доступа к графической сессии')
    path = Path(runtime) / 'serpantinum-vpn-happ.sock'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(path))
            connection.sendall(json.dumps(payload).encode() + b'\n')
            result = b''
            while b'\n' not in result:
                chunk = connection.recv(2048)
                if not chunk or len(result) + len(chunk) > 4096:
                    raise BridgeError('Неверный ответ Happ')
                result += chunk
        response = json.loads(result.split(b'\n', 1)[0])
        if not response.get('ok'):
            raise BridgeError(response.get('error') or 'Happ отклонил команду')
        return response
    except (OSError, ValueError) as error:
        raise BridgeError('Выбор серверов будет доступен после следующего запуска Happ с адаптером') from error
