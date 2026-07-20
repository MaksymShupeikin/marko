"""Application-level authenticated encryption for Yuri's unit cost.

The database stores only AES-256-GCM ciphertext, a random 96-bit nonce, and a
non-secret key identifier.  Associated data binds every ciphertext to its
workspace, catalog item, immutable record id, currency, and format version so
copying a value across tenants or rows fails authentication.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
import re
from types import MappingProxyType
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


COST_ENCRYPTION_ALGORITHM = "AES-256-GCM"
COST_ENCRYPTION_FORMAT_VERSION = 1
COST_ENCRYPTION_NONCE_BYTES = 12
_COST_QUANTUM = Decimal("0.01")
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CostEncryptionConfigurationError(ValueError):
    """The server-side cost keyring is absent or malformed."""


class CostCiphertextError(RuntimeError):
    """Encrypted cost could not be authenticated or decoded."""


@dataclass(frozen=True, slots=True)
class CostKeyring:
    active_key_id: str
    keys: Mapping[str, bytes]

    def key_for(self, key_id: str) -> bytes:
        try:
            return self.keys[key_id]
        except KeyError as exc:
            raise CostCiphertextError("Encrypted cost key is unavailable") from exc


@dataclass(frozen=True, slots=True)
class EncryptedCost:
    ciphertext: bytes
    nonce: bytes
    key_id: str
    algorithm: str = COST_ENCRYPTION_ALGORITHM
    format_version: int = COST_ENCRYPTION_FORMAT_VERSION


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CostEncryptionConfigurationError(
                "Cost encryption keyring contains a duplicate key id"
            )
        result[key] = value
    return result


def _decode_key(value: str) -> bytes:
    if not value or any(character.isspace() for character in value):
        raise CostEncryptionConfigurationError(
            "Each cost encryption key must be base64url without whitespace"
        )
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise CostEncryptionConfigurationError(
            "Each cost encryption key must be valid base64url"
        ) from exc
    if len(decoded) != 32:
        raise CostEncryptionConfigurationError(
            "Each cost encryption key must decode to exactly 32 bytes"
        )
    return decoded


def parse_cost_keyring(*, active_key_id: str, keys_json: str) -> CostKeyring:
    """Parse a versioned keyring without ever returning key material in errors."""
    active = active_key_id.strip()
    if not _KEY_ID.fullmatch(active):
        raise CostEncryptionConfigurationError(
            "COST_ENCRYPTION_ACTIVE_KEY_ID must be a safe non-empty identifier"
        )
    try:
        raw = json.loads(keys_json, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CostEncryptionConfigurationError(
            "COST_ENCRYPTION_KEYS_JSON must be a JSON object"
        ) from exc
    if not isinstance(raw, dict) or not raw or len(raw) > 16:
        raise CostEncryptionConfigurationError(
            "COST_ENCRYPTION_KEYS_JSON must contain between 1 and 16 keys"
        )
    keys: dict[str, bytes] = {}
    for key_id, encoded in raw.items():
        if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
            raise CostEncryptionConfigurationError(
                "Cost encryption key ids must use letters, numbers, dot, dash, or underscore"
            )
        if not isinstance(encoded, str):
            raise CostEncryptionConfigurationError(
                "Each cost encryption key must be a base64url string"
            )
        keys[key_id] = _decode_key(encoded)
    if active not in keys:
        raise CostEncryptionConfigurationError(
            "The active cost encryption key id is absent from the keyring"
        )
    return CostKeyring(active_key_id=active, keys=MappingProxyType(keys))


def canonical_cost(value: Decimal) -> Decimal:
    """Validate the V1 UAH unit-cost precision without silent rounding."""
    if not value.is_finite() or value <= 0:
        raise CostCiphertextError("Unit cost must be a positive finite decimal")
    if value.as_tuple().exponent < -2:
        raise CostCiphertextError("Unit cost supports at most two decimal places")
    try:
        normalized = value.quantize(_COST_QUANTUM)
    except InvalidOperation as exc:
        raise CostCiphertextError("Unit cost cannot be represented") from exc
    if normalized >= Decimal("1000000000000"):
        raise CostCiphertextError("Unit cost exceeds the supported range")
    return normalized


def _associated_data(
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    record_id: UUID,
    key_id: str,
    format_version: int,
) -> bytes:
    return (
        "marko:catalog-item-unit-cost:"
        f"v{format_version}:key={key_id}:workspace={workspace_id}:"
        f"item={catalog_item_id}:record={record_id}:currency=UAH"
    ).encode("ascii")


def encrypt_cost(
    value: Decimal,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    record_id: UUID,
    keyring: CostKeyring,
) -> EncryptedCost:
    normalized = canonical_cost(value)
    key_id = keyring.active_key_id
    nonce = os.urandom(COST_ENCRYPTION_NONCE_BYTES)
    aad = _associated_data(
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        record_id=record_id,
        key_id=key_id,
        format_version=COST_ENCRYPTION_FORMAT_VERSION,
    )
    ciphertext = AESGCM(keyring.key_for(key_id)).encrypt(
        nonce,
        format(normalized, "f").encode("ascii"),
        aad,
    )
    return EncryptedCost(ciphertext=ciphertext, nonce=nonce, key_id=key_id)


def decrypt_cost(
    encrypted: EncryptedCost,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    record_id: UUID,
    keyring: CostKeyring,
) -> Decimal:
    if encrypted.algorithm != COST_ENCRYPTION_ALGORITHM:
        raise CostCiphertextError("Encrypted cost algorithm is unsupported")
    if encrypted.format_version != COST_ENCRYPTION_FORMAT_VERSION:
        raise CostCiphertextError("Encrypted cost format version is unsupported")
    if len(encrypted.nonce) != COST_ENCRYPTION_NONCE_BYTES:
        raise CostCiphertextError("Encrypted cost nonce is invalid")
    aad = _associated_data(
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        record_id=record_id,
        key_id=encrypted.key_id,
        format_version=encrypted.format_version,
    )
    try:
        plaintext = AESGCM(keyring.key_for(encrypted.key_id)).decrypt(
            encrypted.nonce,
            encrypted.ciphertext,
            aad,
        )
        decoded = Decimal(plaintext.decode("ascii"))
        return canonical_cost(decoded)
    except (InvalidTag, UnicodeDecodeError, InvalidOperation) as exc:
        raise CostCiphertextError(
            "Encrypted cost failed authentication or decoding"
        ) from exc


__all__ = [
    "COST_ENCRYPTION_ALGORITHM",
    "COST_ENCRYPTION_FORMAT_VERSION",
    "COST_ENCRYPTION_NONCE_BYTES",
    "CostCiphertextError",
    "CostEncryptionConfigurationError",
    "CostKeyring",
    "EncryptedCost",
    "canonical_cost",
    "decrypt_cost",
    "encrypt_cost",
    "parse_cost_keyring",
]
