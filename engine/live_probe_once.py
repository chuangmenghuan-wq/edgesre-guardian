"""One gated Nebius call, inside the existing R4 loopback HTTP repair test."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parent
PINNED = {
    'guardian.py': 'f062d19d743050433ecc804c22582671d21e2691e6f4db889fc74f3e21535d88',
    'http_lab.py': 'c2f48805a32c1b7cd2f31cc6f55e0b6c01f617a78aebeb0904d3fd82dcfcf119',
}
R4 = ROOT
MODEL = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
URL = 'https://api.tokenfactory.nebius.com/v1'
LOCK = ROOT / 'LIVE_CALL_ATTEMPT_STARTED.json'
RECEIPT = ROOT / 'LIVE_MODEL_RECEIPT.json'
FAILURE = ROOT / 'LIVE_MODEL_FAILURE.json'
FLAGS = ('NEBIUS_ACCOUNT_VERIFIED', 'NEBIUS_FREE_CREDITS_VERIFIED',
         'NEBIUS_BILLING_BLOCK_CONFIRMED', 'NEBIUS_LIVE_ENABLED')


def source_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checks():
    for name, expected in PINNED.items():
        if source_hash(R4 / name) != expected:
            raise RuntimeError('R4_PINNED_SOURCE_CHANGED_' + name)
    out = {'NEBIUS_API_KEY': len(os.getenv('NEBIUS_API_KEY', '')) > 12}
    out.update({name: os.getenv(name) == '1' for name in FLAGS})
    out['DURABLE_NO_RETRY_LOCK_CLEAR'] = not LOCK.exists()
    out['NO_PREVIOUS_LIVE_RECEIPT'] = not RECEIPT.exists()
    return out


def write_once(path, obj):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        json.dump(obj, fp, ensure_ascii=True, indent=2)
        fp.flush()
        os.fsync(fp.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help='Opt in to exactly one potentially billable provider request')
    args = parser.parse_args()
    c = checks()
    missing = [name for name, value in c.items() if not value]
    if not args.execute or missing:
        print(json.dumps({'status': 'BLOCKED_SAFE_NO_NETWORK' if missing else 'READY_REQUIRES_EXPLICIT_EXECUTE',
                          'missing': missing, 'model': MODEL, 'provider_requests_this_run': 0}))
        return 3 if args.execute and missing else 0

    sys.path.insert(0, str(R4))
    import guardian
    import http_lab
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    audit = {}
    provider_info = {}
    decision_info = {}
    # An ambiguous response cannot be retried automatically, even if the process crashes.
    write_once(LOCK, {'status': 'ATTEMPT_STARTED_UNVERIFIED', 'utc': timestamp, 'model': MODEL,
                      'scenario': 'config_drift', 'request_cap': 1})
    try:
        def decide(observation):
            t0 = time.monotonic()
            decision, provider = guardian.live_model(observation, os.environ['NEBIUS_API_KEY'],
                                                     model=MODEL, url=URL, audit=audit)
            audit['model_elapsed_ms'] = round((time.monotonic() - t0) * 1000)
            identity = provider.get('id')
            if not isinstance(identity, str) or not identity.strip():
                raise RuntimeError('MISSING_PROVIDER_RESPONSE_ID')
            provider_info.update(provider)
            decision_info.update(decision)
            return decision, {'provider': 'nebius_token_factory', 'id': identity,
                              'model': provider.get('model'), 'usage': provider.get('usage', {}),
                              'eligible_nebius_inference': True}

        http_receipt = http_lab.run_http_incident('config_drift', decision_provider=decide)
        record = {'status': 'REAL_NEBIUS_RESPONSE', 'utc': timestamp,
                  'request_model': MODEL, 'actual_model': provider_info.get('model'),
                  'provider_id': provider_info['id'], 'usage': provider_info.get('usage', {}),
                  'model_elapsed_ms': audit['model_elapsed_ms'], 'decision': decision_info,
                  'independent_repair_verified': http_receipt['outcome'] == 'VERIFIED_RECOVERY',
                  'repair_outcome': http_receipt['outcome'], 'http_receipt': http_receipt,
                  'provider_audit': audit, 'source_sha256': {name: source_hash(R4 / name) for name in PINNED}}
        record['payload_sha256'] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        write_once(RECEIPT, record)
        print(json.dumps({'status': record['status'], 'provider_id': record['provider_id'],
                          'repair_outcome': record['repair_outcome'], 'receipt_path': str(RECEIPT)}))
        return 0
    except Exception as exc:
        failure = {'status': 'PROVIDER_CALL_FAILED_OR_UNVERIFIED', 'utc': timestamp,
                   'error_type': type(exc).__name__, 'error_code': str(exc)[:150],
                   'provider_audit': audit, 'no_automatic_retries': True,
                   'attempt_lock_path': str(LOCK)}
        write_once(FAILURE, failure)
        print(json.dumps({'status': failure['status'], 'error_type': failure['error_type'],
                          'no_automatic_retries': True, 'failure_path': str(FAILURE)}))
        return 5


if __name__ == '__main__':
    raise SystemExit(main())
