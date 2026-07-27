"""Signing the capability record.

The record is held by the learner and signed by warrant (SPEC section 13): warrant is
the verifier, not the awarding body, and the learner carries the record wherever they
like. Anyone can check the signature against the public key without asking us anything.

With no key configured we still sign, with a deterministic development key, and say so
in the record. A signature that silently means nothing would be worse than no signature.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from warrant.config import settings

_DEV_SEED = hashlib.sha256(b"warrant-development-key-not-for-production").digest()


def _private_key() -> tuple[Ed25519PrivateKey, bool]:
    if settings.signing_key_hex:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(settings.signing_key_hex)), True
    return Ed25519PrivateKey.from_private_bytes(_DEV_SEED), False


def public_key_hex() -> str:
    key, _ = _private_key()
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return raw.hex()


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def sign(payload: dict[str, Any]) -> dict[str, str]:
    key, production = _private_key()
    signature = key.sign(canonical(payload))
    return {
        "algorithm": "ed25519",
        "issuer": settings.record_issuer,
        "held_by": "learner",
        "public_key": public_key_hex(),
        "value": signature.hex(),
        "key_kind": "production" if production else "development",
    }


def verify(payload: dict[str, Any], signature: dict[str, str]) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(signature["public_key"]))
        public.verify(bytes.fromhex(signature["value"]), canonical(payload))
    except Exception:
        return False
    return True
