"""Security and contract tests for server-side encrypted unit cost."""

from __future__ import annotations

import base64
from dataclasses import replace
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from marko.api.schemas.pricing import (
    CatalogItemOverrideRequest,
    PricingContextInput,
)
from marko.core.config import Settings
from marko.core.cost_encryption import (
    CostCiphertextError,
    CostEncryptionConfigurationError,
    decrypt_cost,
    encrypt_cost,
    parse_cost_keyring,
)
from marko.infrastructure.db.models import CatalogItemCostRecord
from marko.services.catalog_costs import (
    add_cost_clear_record,
    add_encrypted_cost_record,
)
from marko.services.catalog_costs import decrypt_cost_record
from marko.services.cost_privacy import (
    CostPrivacyBlocked,
    privacy_safe_validation_errors,
    require_server_cost_input_allowed,
)


def _encoded_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode().rstrip("=")


def _keyring(*, active: str = "cost-v1", include_old: bool = False):
    keys = {active: _encoded_key(2)}
    if include_old:
        keys["cost-v0"] = _encoded_key(1)
    return parse_cost_keyring(active_key_id=active, keys_json=json.dumps(keys))


def _server_settings(*, active: str = "cost-v1", include_old: bool = False) -> Settings:
    keys = {active: _encoded_key(2)}
    if include_old:
        keys["cost-v0"] = _encoded_key(1)
    return Settings(
        cost_privacy_mode="SERVER_SIDE_ENCRYPTED",
        cost_encryption_active_key_id=active,
        cost_encryption_keys_json=json.dumps(keys),
    )


def test_aes_gcm_round_trip_uses_unique_nonce_and_row_bound_aad() -> None:
    workspace_id = uuid4()
    item_id = uuid4()
    record_id = uuid4()
    keyring = _keyring()

    first = encrypt_cost(
        Decimal("987.65"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=record_id,
        keyring=keyring,
    )
    second = encrypt_cost(
        Decimal("987.65"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=record_id,
        keyring=keyring,
    )

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert b"987.65" not in first.ciphertext
    assert decrypt_cost(
        first,
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=record_id,
        keyring=keyring,
    ) == Decimal("987.65")
    with pytest.raises(CostCiphertextError):
        decrypt_cost(
            first,
            workspace_id=uuid4(),
            catalog_item_id=item_id,
            record_id=record_id,
            keyring=keyring,
        )


def test_tampering_is_rejected_without_echoing_plaintext() -> None:
    workspace_id = uuid4()
    item_id = uuid4()
    record_id = uuid4()
    keyring = _keyring()
    encrypted = encrypt_cost(
        Decimal("123.45"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=record_id,
        keyring=keyring,
    )
    tampered = replace(
        encrypted,
        ciphertext=encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1]),
    )

    with pytest.raises(CostCiphertextError) as error:
        decrypt_cost(
            tampered,
            workspace_id=workspace_id,
            catalog_item_id=item_id,
            record_id=record_id,
            keyring=keyring,
        )

    assert "123.45" not in str(error.value)


def test_key_rotation_keeps_old_records_readable_and_uses_active_key_for_writes() -> (
    None
):
    workspace_id = uuid4()
    item_id = uuid4()
    old_record_id = uuid4()
    old_keyring = parse_cost_keyring(
        active_key_id="cost-v0",
        keys_json=json.dumps({"cost-v0": _encoded_key(1)}),
    )
    old_record = encrypt_cost(
        Decimal("500.00"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=old_record_id,
        keyring=old_keyring,
    )
    rotated = _keyring(include_old=True)
    new_record = encrypt_cost(
        Decimal("600.00"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=uuid4(),
        keyring=rotated,
    )

    assert old_record.key_id == "cost-v0"
    assert new_record.key_id == "cost-v1"
    assert decrypt_cost(
        old_record,
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=old_record_id,
        keyring=rotated,
    ) == Decimal("500.00")


@pytest.mark.parametrize(
    ("active", "payload"),
    (
        ("cost-v1", "{}"),
        ("missing", json.dumps({"cost-v1": _encoded_key(2)})),
        ("cost-v1", json.dumps({"cost-v1": "too-short"})),
        ("cost-v1", '{"cost-v1":"a","cost-v1":"b"}'),
    ),
)
def test_invalid_keyrings_fail_closed_without_key_material(
    active: str, payload: str
) -> None:
    with pytest.raises(CostEncryptionConfigurationError) as error:
        parse_cost_keyring(active_key_id=active, keys_json=payload)

    assert _encoded_key(2) not in str(error.value)


class _CaptureSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def test_persistence_record_contains_ciphertext_only_and_clear_is_a_tombstone() -> None:
    session = _CaptureSession()
    settings = _server_settings()
    workspace_id = uuid4()
    item_id = uuid4()
    user_id = uuid4()

    encrypted = add_encrypted_cost_record(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        user_id=user_id,
        cost=Decimal("987.65"),
        reason="operator update",
        settings=settings,
    )
    cleared = add_cost_clear_record(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        user_id=user_id,
        reason="operator clear",
        settings=settings,
    )

    assert isinstance(encrypted, CatalogItemCostRecord)
    assert encrypted.action == "SET"
    assert encrypted.ciphertext is not None
    assert b"987.65" not in encrypted.ciphertext
    assert not hasattr(encrypted, "cost")
    assert cleared.action == "CLEAR"
    assert cleared.ciphertext is None
    assert cleared.nonce is None
    assert session.added == [encrypted, cleared]


def test_server_mode_allows_cost_only_with_valid_external_keyring() -> None:
    settings = _server_settings()

    require_server_cost_input_allowed(Decimal("987.65"), settings=settings)
    assert "987.65" not in repr(settings)
    assert _encoded_key(2) not in repr(settings)

    with pytest.raises(CostPrivacyBlocked):
        require_server_cost_input_allowed(
            Decimal("987.65"),
            settings=Settings(cost_privacy_mode="LOCAL_DEVICE_ONLY"),
        )


def test_non_persistence_pricing_api_rejects_raw_cost_and_redacts_validation_input() -> (
    None
):
    with pytest.raises(ValidationError) as error:
        PricingContextInput.model_validate(
            {
                "sku": "SKU-1",
                "category": "parts",
                "current_price": "1000",
                "cost": "987.65",
            }
        )

    safe = privacy_safe_validation_errors(error.value.errors())
    serialized = json.dumps(safe)
    assert "987.65" not in serialized
    assert all("input" not in entry for entry in safe)

    with pytest.raises(ValidationError):
        CatalogItemOverrideRequest.model_validate(
            {
                "below_cost_floor": "900",
                "reason": "legacy payload",
            }
        )


def test_decrypt_cost_record_honours_the_record_it_is_given() -> None:
    """Прогон считает по себестоимости, замороженной на старте.

    До появления этого шва расчёт звал ``get_decrypted_catalog_cost``, который
    всегда берёт последнюю запись. Себестоимость, поданная оператором уже во
    время расчёта, попадала в идущий прогон, и повторить его было нельзя.
    """

    workspace_id = uuid4()
    item_id = uuid4()
    frozen_id = uuid4()
    later_id = uuid4()
    settings = _server_settings()
    keyring = settings.cost_keyring

    frozen = encrypt_cost(
        Decimal("100.00"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=frozen_id,
        keyring=keyring,
    )
    later = encrypt_cost(
        Decimal("999.00"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=later_id,
        keyring=keyring,
    )

    def _record(record_id, encrypted):
        return CatalogItemCostRecord(
            id=record_id,
            workspace_id=workspace_id,
            catalog_item_id=item_id,
            action="SET",
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_id=encrypted.key_id,
            algorithm=encrypted.algorithm,
            format_version=encrypted.format_version,
        )

    assert decrypt_cost_record(
        _record(frozen_id, frozen),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        settings=settings,
    ) == Decimal("100.00")
    # Более свежая запись существует, но расчёт её не спрашивал.
    assert decrypt_cost_record(
        _record(later_id, later),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        settings=settings,
    ) == Decimal("999.00")
    # Снятая себестоимость остаётся снятой.
    assert (
        decrypt_cost_record(
            CatalogItemCostRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                catalog_item_id=item_id,
                action="CLEAR",
            ),
            workspace_id=workspace_id,
            catalog_item_id=item_id,
            settings=settings,
        )
        is None
    )


def test_decrypt_cost_record_still_refuses_when_privacy_mode_is_off() -> None:
    """Новый шов не ослабляет приватность: проверка режима осталась внутри."""

    workspace_id = uuid4()
    item_id = uuid4()
    record_id = uuid4()
    encrypted = encrypt_cost(
        Decimal("10.00"),
        workspace_id=workspace_id,
        catalog_item_id=item_id,
        record_id=record_id,
        keyring=_keyring(),
    )
    with pytest.raises(CostPrivacyBlocked):
        decrypt_cost_record(
            CatalogItemCostRecord(
                id=record_id,
                workspace_id=workspace_id,
                catalog_item_id=item_id,
                action="SET",
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_id=encrypted.key_id,
                algorithm=encrypted.algorithm,
                format_version=encrypted.format_version,
            ),
            workspace_id=workspace_id,
            catalog_item_id=item_id,
            settings=Settings(cost_privacy_mode="UNDECIDED"),
        )
