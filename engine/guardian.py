"""EdgeSRE Guardian — isolated competition adapter. No production modifications.

The mock scenario is a deterministic digital twin (explicitly NOT live Nebius inference).
A live eligible path requires NEBIUS_API_KEY and a successful Token Factory call.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MODEL = os.getenv('NEBIUS_MODEL', 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B')
BASE_URL = os.getenv('NEBIUS_BASE_URL', 'https://api.tokenfactory.nebius.com/v1').rstrip('/')
SCENARIOS = ('config_drift', 'false_green', 'dependency_outage', 'healthy')
ACTIONS = {'set_cache_endpoint', 'restart_service', 'abstain'}
APPROVED_NEBIUS_ENDPOINTS = frozenset({
    'https://api.tokenfactory.nebius.com/v1',
    'https://api.tokenfactory.us-central1.nebius.com/v1',
})
LIVE_CALL_LIMIT = 1
_live_call_lock = threading.Lock()
_live_call_count = 0


def guard_real_inference(api_key: str, model: str, endpoint: str) -> None:
    """Every condition must be explicitly met before a billable network request."""
    if not api_key:
        raise RuntimeError('NEBIUS_API_KEY_NOT_CONFIGURED')
    if os.getenv('NEBIUS_LIVE_ENABLED') != '1':
        raise RuntimeError('LIVE_GATE_DISABLED')
    if os.getenv('NEBIUS_FREE_CREDITS_VERIFIED') != '1':
        raise RuntimeError('FREE_CREDIT_BALANCE_NOT_VERIFIED')
    if endpoint.rstrip('/') not in APPROVED_NEBIUS_ENDPOINTS:
        raise RuntimeError('UNAPPROVED_NEBIUS_ENDPOINT')
    if not isinstance(model, str) or not model.lower().startswith('nvidia/'):
        raise RuntimeError('NVIDIA_MODEL_REQUIRED')


def reserve_one_live_call() -> None:
    """Local-process cap to prevent repeated paid calls from the demo."""
    global _live_call_count
    with _live_call_lock:
        if _live_call_count >= LIVE_CALL_LIMIT:
            raise RuntimeError('NEBIUS_LIVE_CALL_LIMIT_REACHED')
        _live_call_count += 1



def initial_state(scenario: str) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError('UNKNOWN_SCENARIO')
    return {
        'process_running': True,
        'cache_endpoint': 'cache.bad.local' if scenario in ('config_drift', 'false_green') else 'cache.prod.local',
        'dependency_online': scenario != 'dependency_outage',
        'business_route_ok': scenario != 'false_green',
        'restart_count': 0,
    }


def probe(state: dict) -> dict:
    """Independent business-level verifier, intentionally distinct from agent's choice."""
    process = bool(state['process_running'])
    dependency = bool(state['dependency_online'])
    config = state['cache_endpoint'] == 'cache.prod.local'
    business = bool(state['business_route_ok'])
    return {
        'process_healthy': process,
        'dependency_healthy': dependency,
        'config_healthy': config,
        'business_transaction_ok': process and dependency and config and business,
        'healthy': process and dependency and config and business,
    }


def make_observation(state: dict) -> dict:
    p = probe(state)
    return {
        'metrics': {'error_rate': 0 if p['healthy'] else 0.67, 'process_up': int(p['process_healthy'])},
        'logs': [f"cache endpoint={state['cache_endpoint']}",
                 f"dependency={state['dependency_online']}",
                 'payment order validation: PASS' if p['business_transaction_ok'] else 'payment order validation: FAIL'],
        'configuration': {'cache_endpoint': state['cache_endpoint']},
        'health': p,
    }


def normalize_action(raw: Any) -> tuple[str, dict]:
    """Deny any action outside an exact small allowlist; never execute shell commands."""
    if not isinstance(raw, dict):
        raise ValueError('MALFORMED_MODEL_DECISION')
    action = raw.get('action')
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError('UNAPPROVED_MODEL_ACTION')
    if set(raw) - {'action', 'args', 'reason'}:
        raise ValueError('EXTRA_MODEL_DECISION_FIELDS')
    if 'reason' in raw and (not isinstance(raw['reason'], str) or len(raw['reason']) > 500):
        raise ValueError('UNSAFE_MODEL_REASON')
    args = raw.get('args', {})
    if not isinstance(args, dict):
        raise ValueError('MALFORMED_ARGS')
    if action == 'set_cache_endpoint':
        if set(args) != {'endpoint'} or args['endpoint'] != 'cache.prod.local':
            raise ValueError('UNSAFE_ENDPOINT')
    elif args:
        raise ValueError('UNEXPECTED_ARGS')
    return action, args


def simulate_model(observation: dict) -> dict:
    if observation['configuration']['cache_endpoint'] != 'cache.prod.local':
        return {'action': 'set_cache_endpoint', 'args': {'endpoint': 'cache.prod.local'},
                'reason': 'Observed configuration drift'}
    if not observation['health']['dependency_healthy']:
        return {'action': 'restart_service', 'args': {},
                'reason': 'Test bounded recovery against a dependency failure'}
    return {'action': 'abstain', 'args': {}, 'reason': 'No allowlisted repair indicated'}


def live_model(observation: dict, api_key: str, model: str = MODEL, url: str = BASE_URL,
               audit: dict | None = None) -> tuple[dict, dict]:
    """Nebius OpenAI-compatible Token Factory call. Never emit the API key."""
    guard_real_inference(api_key, model, url)
    reserve_one_live_call()
    body = json.dumps({
        'model': model,
        'max_tokens': 700,
        'messages': [
            {'role': 'system', 'content': (
                'You are an SRE incident triage model in a read-only simulator. '
                'Return only a JSON object with keys action, args, reason. '
                'Allowed actions: set_cache_endpoint with args {"endpoint":"cache.prod.local"}; '
                'restart_service with args {}; abstain with args {}. '
                'Never issue shell commands, credentials, web access or instructions outside these actions. '
                'Be conservative if evidence is insufficient.')},
            {'role': 'user', 'content': json.dumps(observation, ensure_ascii=False)},
        ],
    }).encode('utf-8')
    if audit is not None:
        audit['request_body_sha256'] = hashlib.sha256(body).hexdigest()
    req = urllib.request.Request(url + '/chat/completions', body, method='POST', headers={
        'Authorization': 'Bearer ' + api_key,
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw_body = resp.read(250_001)
            if len(raw_body) > 250_000:
                raise RuntimeError('NEBIUS_RESPONSE_TOO_LARGE')
            if audit is not None:
                audit['http_status'] = resp.status
                audit['response_body_sha256'] = hashlib.sha256(raw_body).hexdigest()
            response = json.loads(raw_body.decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError('NEBIUS_HTTP_' + str(exc.code)) from None
    except Exception as exc:
        raise RuntimeError('NEBIUS_INFERENCE_FAILED_' + type(exc).__name__) from None
    if audit is not None:
        # The request credential is sent only as a header. Keep the provider body,
        # but remove any unexpected credential-shaped fields before persistence.
        def redact(value):
            if isinstance(value, dict):
                return {k: ('[REDACTED]' if k.lower() in {'api_key','authorization','access_token','refresh_token','cookie','set-cookie'} else redact(v))
                        for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        audit['redacted_provider_body'] = redact(response)
    choices = response.get('choices') or []
    if not choices:
        raise RuntimeError('NEBIUS_EMPTY_RESPONSE')
    content = (choices[0].get('message') or {}).get('content') or ''
    if not isinstance(content, str):
        raise RuntimeError('NEBIUS_UNPARSABLE_RESPONSE')
    candidate = content.strip()
    if candidate.startswith('```'):
        candidate = candidate.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        decision = json.loads(candidate)
    except ValueError:
        raise RuntimeError('NEBIUS_NON_JSON_DECISION') from None
    return decision, {'model': response.get('model', model), 'id': response.get('id'),
                      'usage': response.get('usage', {}), 'provider': 'nebius_token_factory'}


def apply_allowlisted(state: dict, action: str, args: dict) -> None:
    if action == 'set_cache_endpoint':
        state['cache_endpoint'] = args['endpoint']
    elif action == 'restart_service':
        state['restart_count'] += 1
        state['process_running'] = True
    elif action == 'abstain':
        return
    else:
        raise AssertionError('UNREACHABLE_UNAPPROVED_ACTION')


def run_incident(scenario: str, mode: str = 'fixture', decision_override: dict | None = None,
                 api_key: str = '', model: str = MODEL) -> dict:
    if mode not in ('fixture', 'live'):
        raise ValueError('UNKNOWN_MODE')
    state = initial_state(scenario)
    original = copy.deepcopy(state)
    steps: list[dict] = []
    last_hash = '0' * 64

    def record(stage: str, payload: dict) -> None:
        nonlocal last_hash
        event = {'seq': len(steps) + 1, 'stage': stage, 'data': payload, 'previous_sha256': last_hash}
        last_hash = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(',', ':'),
                                              ensure_ascii=True).encode()).hexdigest()
        event['sha256'] = last_hash
        steps.append(event)

    observed = make_observation(state)
    record('INJECT_FAULT', {'scenario': scenario, 'mode': mode, 'start_health': observed['health']})
    record('OBSERVE', observed)
    provider = {'provider': 'deterministic_fixture', 'eligible_nebius_inference': False}
    try:
        if decision_override is not None:
            decision = decision_override
            provider = {'provider': 'test_override', 'eligible_nebius_inference': False}
        elif mode == 'fixture':
            decision = simulate_model(observed)
        else:
            decision, provider = live_model(observed, api_key=api_key, model=model)
            provider['eligible_nebius_inference'] = True
        record('MODEL_PROPOSAL', {'decision': decision, 'provider': provider})
        action, args = normalize_action(decision)
        record('SAFETY_GATE', {'status': 'ALLOW' if action != 'abstain' else 'ABSTAIN',
                               'action': action, 'args': args})
        if observed['health']['healthy']:
            outcome = 'HEALTHY_NO_ACTION'
        elif action == 'abstain':
            outcome = 'ABSTAIN_NO_REPAIR'
        else:
            dry = copy.deepcopy(state)
            apply_allowlisted(dry, action, args)
            record('DRY_RUN', {'simulated_result': probe(dry)})
            apply_allowlisted(state, action, args)
            record('EXECUTE_ALLOWLISTED', {'action': action, 'args': args})
            post = probe(state)
            record('INDEPENDENT_VERIFY', {'business_probe': post})
            if post['healthy']:
                outcome = 'VERIFIED_RECOVERY'
            else:
                state = original
                record('ROLLBACK', {'restored_original': state == original,
                                    'health_after_rollback': probe(state)})
                outcome = 'ROLLED_BACK_NOT_RECOVERED'
    except Exception as exc:
        # Fail closed: never claim recovery on invalid, unreachable or unauthenticated inference.
        state = original
        record('FAIL_CLOSED', {'reason_code': str(exc)[:150], 'unchanged': state == original})
        outcome = 'BLOCKED_FAIL_CLOSED'

    final_health = probe(state)
    if outcome == 'VERIFIED_RECOVERY' and not final_health['healthy']:
        raise AssertionError('FALSE_SUCCESS_FORBIDDEN')
    record('FINAL', {'outcome': outcome, 'health': final_health,
                     'eligible_live_call': bool(provider.get('eligible_nebius_inference'))})
    return {
        'scenario': scenario, 'mode': mode, 'outcome': outcome, 'provider': provider,
        'original': original, 'final_state': state, 'health': final_health,
        'eligible_live_call': bool(provider.get('eligible_nebius_inference')),
        'events': steps, 'ledger_head_sha256': last_hash,
    }


def verify_chain(events: list[dict]) -> bool:
    prev = '0' * 64
    for index, event in enumerate(events, start=1):
        if event.get('seq') != index or event.get('previous_sha256') != prev:
            return False
        payload = {k: v for k, v in event.items() if k != 'sha256'}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=True).encode()).hexdigest()
        if expected != event.get('sha256'):
            return False
        prev = expected
    return True

def verify_incident_receipt(receipt: dict) -> bool:
    """Check internal consistency, not cryptographic source authenticity."""
    try:
        if not isinstance(receipt, dict):return False
        events=receipt['events']
        if not isinstance(events,list) or len(events)<3 or not verify_chain(events):return False
        if events[-1]['stage']!='FINAL' or events[0]['stage']!='INJECT_FAULT':return False
        if receipt['ledger_head_sha256']!=events[-1]['sha256']:return False
        stages=[e['stage'] for e in events]
        if 'MODEL_PROPOSAL' not in stages and 'FAIL_CLOSED' not in stages:return False
        if receipt['scenario'] not in SCENARIOS or receipt['mode'] not in ('fixture','live'):return False
        if events[0]['data'].get('scenario')!=receipt['scenario'] or events[0]['data'].get('mode')!=receipt['mode']:return False
        if receipt['outcome'] not in {'VERIFIED_RECOVERY','ROLLED_BACK_NOT_RECOVERED','ABSTAIN_NO_REPAIR','HEALTHY_NO_ACTION','BLOCKED_FAIL_CLOSED'}:return False
        if receipt['health']!=probe(receipt['final_state']):return False
        last=events[-1]['data']
        if last!={'outcome':receipt['outcome'],'health':receipt['health'],'eligible_live_call':receipt['eligible_live_call']}:return False
        if receipt['outcome']=='VERIFIED_RECOVERY':
            if not receipt['health']['business_transaction_ok'] or 'INDEPENDENT_VERIFY' not in stages:return False
        if receipt['outcome'] in ('BLOCKED_FAIL_CLOSED','ROLLED_BACK_NOT_RECOVERED') and receipt['final_state']!=receipt['original']:return False
        if receipt['outcome']=='HEALTHY_NO_ACTION' and (not receipt['health']['healthy'] or 'EXECUTE_ALLOWLISTED' in stages):return False
        proposal_events=[e for e in events if e['stage']=='MODEL_PROPOSAL']
        if proposal_events and proposal_events[-1]['data'].get('provider')!=receipt['provider']:return False
        eligible=receipt['eligible_live_call']
        if not isinstance(eligible,bool):return False
        if eligible and (receipt['mode']!='live' or receipt['provider'].get('provider')!='nebius_token_factory'):return False
        if receipt['mode']=='fixture' and eligible:return False
        return True
    except (TypeError,ValueError,KeyError,IndexError,AttributeError):
        return False


class LocalHandler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, code: int = 200, typ: str = 'application/json; charset=utf-8') -> None:
        self.send_response(code)
        self.send_header('Content-Type', typ)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', 'http://127.0.0.1:8766')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ('/', '/index.html'):
            self._send((HERE / 'index.html').read_bytes(), typ='text/html; charset=utf-8')
        elif self.path == '/health':
            self._send(json.dumps({'server': 'ok', 'live_key_configured': bool(os.getenv('NEBIUS_API_KEY')),
                                   'official_nebius_call_verified': False}).encode())
        else:
            self._send(b'{"error":"not_found"}', code=404)

    def do_POST(self) -> None:
        if self.path != '/api/run':
            self._send(b'{"error":"not_found"}', code=404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 4000 or size < 2:
                raise ValueError('INVALID_REQUEST_SIZE')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or set(data) != {'scenario', 'mode'}:
                raise ValueError('INVALID_REQUEST_FIELDS')
            output = run_incident(str(data['scenario']), str(data['mode']),
                                  api_key=os.getenv('NEBIUS_API_KEY', ''))
            self._send(json.dumps(output, ensure_ascii=False).encode())
        except Exception as exc:
            self._send(json.dumps({'error': type(exc).__name__ + ':' + str(exc)[:100]}).encode(), code=400)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if args.smoke:
        outputs = []
        for case in SCENARIOS:
            result = run_incident(case)
            assert verify_chain(result['events'])
            outputs.append({'scenario': case, 'outcome': result['outcome'], 'chain_valid': True})
        print(json.dumps({'smoke_pass': True, 'cases': outputs}))
    elif args.serve:
        print(f'Local demo: http://127.0.0.1:{args.port}', flush=True)
        ThreadingHTTPServer(('127.0.0.1', args.port), LocalHandler).serve_forever()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
