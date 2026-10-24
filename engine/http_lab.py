"""Local *real HTTP* fault/repair experiment, loopback only; NOT production nor Nebius."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from guardian import SCENARIOS, initial_state, normalize_action, simulate_model, verify_chain


def stable_sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run_http_incident(scenario: str, decision_override: dict | None = None,
                      decision_provider: Callable[[dict], tuple[dict, dict]] | None = None) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError('UNKNOWN_SCENARIO')
    if decision_override is not None and decision_provider is not None:
        raise ValueError('AMBIGUOUS_DECISION_SOURCE')
    state = initial_state(scenario)
    with tempfile.TemporaryDirectory(prefix='edgesre_r4_http_') as temp:
        config = Path(temp) / 'payment-config.json'
        def save_config():
            incoming = Path(temp) / 'config.new'
            incoming.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
            incoming.replace(config)
        save_config()
        original_bytes = config.read_bytes()

        class PaymentHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                s = json.loads(config.read_text(encoding='utf-8'))
                if self.path == '/health':
                    code = 200 if s['process_running'] else 503
                elif self.path == '/checkout':
                    if not s['process_running'] or not s['dependency_online']:
                        code = 503
                    elif s['cache_endpoint'] != 'cache.prod.local':
                        code = 503
                    elif not s['business_route_ok']:
                        code = 502
                    else:
                        code = 200
                else:
                    code = 404
                data = json.dumps({'status': 'ok' if code == 200 else 'failed', 'path': self.path, 'status_code': code}).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), PaymentHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        events: list[dict] = []
        prev = '0' * 64
        def record(stage, data):
            nonlocal prev
            e = {'seq': len(events) + 1, 'stage': stage, 'data': data, 'previous_sha256': prev}
            prev = stable_sha(e)
            e['sha256'] = prev
            events.append(e)
        def status(route: str) -> int:
            try:
                with urllib.request.urlopen(base + route, timeout=3) as response:
                    return response.status
            except urllib.error.HTTPError as e:
                return e.code
        try:
            before = {'process_http': status('/health'), 'business_http': status('/checkout')}
            record('HTTP_OBSERVE', {'scenario': scenario, 'before': before, 'config_sha256': hashlib.sha256(original_bytes).hexdigest()})
            observation = {
                'configuration': {'cache_endpoint': state['cache_endpoint']},
                'health': {'dependency_healthy': state['dependency_online']},
                'real_http': before,
            }
            record('MODEL_INPUT', observation)
            if decision_provider is not None:
                decision, provider = decision_provider(observation)
            elif decision_override is not None:
                decision, provider = decision_override, 'test_override'
            else:
                decision, provider = simulate_model(observation), 'offline_fixture_not_nebius'
            record('MODEL_PROPOSAL', {'decision': decision, 'provider': provider})
            try:
                action, args = normalize_action(decision)
                record('POLICY_CHECK', {'action': action, 'accepted': True})
                if before['business_http'] == 200:
                    outcome = 'HEALTHY_NO_ACTION'
                elif action == 'abstain':
                    outcome = 'ABSTAIN_NO_REPAIR'
                else:
                    if action == 'set_cache_endpoint':
                        state['cache_endpoint'] = args['endpoint']
                    elif action == 'restart_service':
                        state['restart_count'] += 1
                    save_config()
                    record('WRITE_LOCAL_CONFIG', {'action': action, 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest()})
                    after = {'process_http': status('/health'), 'business_http': status('/checkout')}
                    record('INDEPENDENT_HTTP_VERIFY', after)
                    if after['business_http'] == 200 and after['process_http'] == 200:
                        outcome = 'VERIFIED_RECOVERY'
                    else:
                        config.write_bytes(original_bytes)
                        record('ROLLBACK_FILE', {'restored_original': config.read_bytes() == original_bytes})
                        outcome = 'ROLLED_BACK_NOT_RECOVERED'
            except (ValueError, TypeError) as exc:
                config.write_bytes(original_bytes)
                record('FAIL_CLOSED', {'error_code': str(exc)[:100]})
                outcome = 'BLOCKED_FAIL_CLOSED'
            end = {'process_http': status('/health'), 'business_http': status('/checkout')}
            record('FINAL_HTTP', {'outcome': outcome, 'after': end})
            if outcome == 'VERIFIED_RECOVERY' and end['business_http'] != 200:
                raise AssertionError('FALSE_SUCCESS_FORBIDDEN')
            receipt = {'scenario': scenario, 'outcome': outcome, 'before': before, 'after': end,
                       'config_rolled_back': config.read_bytes() == original_bytes,
                       'events': events, 'head_sha256': prev,
                       'local_tcp_requests': True, 'provider': provider,
                       'real_nebius_calls': int(isinstance(provider, dict) and provider.get('eligible_nebius_inference') is True)}
            if not verify_chain(events):
                raise AssertionError('BROKEN_EVENT_CHAIN')
            return receipt
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=4)
