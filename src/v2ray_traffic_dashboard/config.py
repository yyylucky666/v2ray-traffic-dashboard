import ipaddress
import json
from pathlib import Path
import re


def endpoint(value):
    host, port = value.rsplit(':', 1)
    host = host.strip('[]')
    if host != 'localhost' and not ipaddress.ip_address(host).is_loopback:
        raise ValueError('Statistics API must listen on loopback')
    if not 1 <= int(port) <= 65535:
        raise ValueError('Invalid statistics API port')
    return host, int(port)


def load(path):
    data = json.loads(Path(path).read_text())
    for key in ('state_dir', 'web_dir', 'v2ray_binary'):
        if not Path(data[key]).is_absolute():
            raise ValueError(key + ' must be an absolute path')
    endpoint(data['stats_server'])
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+', data['v2ray_service']):
        raise ValueError('Invalid systemd service name')
    if not isinstance(data.get('retention_days', 400), int) or not 1 <= data.get('retention_days', 400) <= 3650:
        raise ValueError('retention_days must be between 1 and 3650')
    categories = data['categories']
    if not categories or len(categories) > 64:
        raise ValueError('Use 1 to 64 categories')
    for field in ('id', 'tag'):
        values = [c[field] for c in categories]
        if len(values) != len(set(values)) or any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', v) for v in values):
            raise ValueError('Category ' + field + ' must be unique safe identifiers')
    for c in categories:
        if not isinstance(c.get('label'), str) or not c['label'].strip():
            raise ValueError('Category label is required')
        if not isinstance(c.get('domains'), list) or any(not isinstance(d, str) or not d for d in c['domains']):
            raise ValueError('Category domains must be a list of nonempty strings')
    if any(not c['domains'] for c in categories[:-1]) or categories[-1]['domains']:
        raise ValueError('Exactly one catch-all category with empty domains must be last')
    return data
