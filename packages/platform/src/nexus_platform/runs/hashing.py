"""Run hashing: one application responsibility with legacy function compatibility."""
from __future__ import annotations
import hashlib
import json
from typing import Any


def digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
