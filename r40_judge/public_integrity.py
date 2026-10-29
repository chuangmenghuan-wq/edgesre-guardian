"""Verify the local lab's event hash chain without provider transport code."""
from __future__ import annotations

import hashlib
import json


def verify_chain(events: list[dict]) -> bool:
    prev = "0" * 64
    for index, event in enumerate(events, start=1):
        if event.get("seq") != index or event.get("previous_sha256") != prev:
            return False
        payload = {k: v for k, v in event.items() if k != "sha256"}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=True).encode()).hexdigest()
        if expected != event.get("sha256"):
            return False
        prev = expected
    return True
