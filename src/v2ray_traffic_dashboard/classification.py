"""Generate a private candidate; never modify a live config or restart V2Ray."""
import copy
from .config import endpoint


def candidate(original, config, direct_tag='direct'):
    result = copy.deepcopy(original)
    if any(x.get('tag') == 'vtd-classification' for x in original.get('inbounds', [])):
        raise ValueError('Classification inbound tag already exists')
    outbounds = result.get('outbounds', [])
    direct = next((x for x in outbounds if x.get('tag') == direct_tag), None)
    if direct is None or direct.get('protocol') != 'freedom':
        raise ValueError('The selected outbound must be an existing freedom outbound')
    existing = {x.get('tag') for x in outbounds}
    if existing.intersection(c['tag'] for c in config['categories']):
        raise ValueError('Category outbound tags already exist; refusing duplicate integration')
    host, port = endpoint(config['stats_server'])
    if host == 'localhost':
        host = '127.0.0.1'
    api = result.get('api')
    api_rule = []
    if api:
        matches = [x for x in result.get('inbounds', []) if x.get('port') == port]
        if not matches or any(x.get('listen') not in ('127.0.0.1', '::1', 'localhost') for x in matches):
            raise ValueError('Existing API needs an explicit matching loopback inbound')
        if not api.get('tag'):
            raise ValueError('Existing API needs a tag')
        if 'StatsService' not in api.setdefault('services', []):
            api['services'].append('StatsService')
        rules = original.get('routing', {}).get('rules', [])
        for inbound in matches:
            if not inbound.get('tag') or not any(r.get('outboundTag') == api['tag'] and inbound['tag'] in r.get('inboundTag', []) for r in rules):
                raise ValueError('Existing API inbound needs a routing rule to the API tag')
    else:
        if any(x.get('port') == port for x in result.get('inbounds', [])):
            raise ValueError('API port conflicts with an existing inbound')
        if {'vtd-api', 'vtd-api-in'}.intersection(existing | {x.get('tag') for x in result.get('inbounds', [])}):
            raise ValueError('API tags already exist')
        result['api'] = {'tag': 'vtd-api', 'services': ['StatsService']}
        result.setdefault('inbounds', []).append({'tag': 'vtd-api-in', 'listen': host, 'port': port,
            'protocol': 'dokodemo-door', 'settings': {'address': host}})
        api_rule = [{'type': 'field', 'inboundTag': ['vtd-api-in'], 'outboundTag': 'vtd-api'}]
    result.setdefault('stats', {})
    policy = result.setdefault('policy', {}).setdefault('system', {})
    policy.update(statsOutboundUplink=True, statsOutboundDownlink=True)
    cloned = copy.deepcopy(direct)
    direct.clear()
    direct.update(tag=direct_tag, protocol='loopback', settings={'inboundTag': 'vtd-classification'})
    rules = []
    for c in config['categories']:
        outbound = copy.deepcopy(cloned)
        outbound['tag'] = c['tag']
        outbounds.append(outbound)
        rule = {'type': 'field', 'inboundTag': ['vtd-classification'], 'outboundTag': c['tag']}
        if c['domains']:
            rule['domain'] = c['domains']
        else:
            rule['network'] = 'tcp,udp'
        rules.append(rule)
    routing = result.setdefault('routing', {})
    if routing.get('balancers') or any('balancerTag' in r for r in routing.get('rules', [])):
        raise ValueError('Balancer configurations need manual integration and are not supported')
    routing['rules'] = rules + api_rule + copy.deepcopy(original.get('routing', {}).get('rules', []))
    return result
