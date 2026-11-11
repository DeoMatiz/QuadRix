# Тесты порта horizon-client-core/src/uuid.rs → quadrix/core/uuid.py.
#
# Проверяем вандаловы функции `uuid_text` / `uuid_from_text` (четыре int,
# дефисы игнорируются, отклонение не-hex/многобайтных/пустых строк) и класс
# `UUID` (from_str/from_bytes/from_int, to_str/to_bytes/to_int, version/variant,
# msb/lsb). Ожидаемые значения взяты из стандарта и из тестов Rust, а не из
# кода под тестом.

from __future__ import annotations

import uuid as py_uuid

import pytest

from quadrix.core.uuid import UUID, uuid_from_text, uuid_text

CANON = "550e8400-e29b-41d4-a716-446655440000"


# ── uuid_text / uuid_from_text (Rust-функции) ─────────────────────────────
def test_from_text_parses_hex_and_dashes_round_trip():
    # Rust: [0x01234567, -0x76543211, 0x01234567, -0x76543211].
    u = [0x01234567, -0x76543211, 0x01234567, -0x76543211]
    text = uuid_text(u)
    assert uuid_from_text(text) == u
    undashed = text.replace("-", "")
    assert uuid_from_text(undashed) == u


def test_from_text_rejects_multibyte_and_non_hex():
    assert uuid_from_text("€€€€€€€€€€aa") is None
    assert uuid_from_text("€€€€€€€€€€aa----") is None
    assert uuid_from_text("+0000001-0000-0000-0000-000000000000") is None
    assert uuid_from_text("00000000-0000-0000-0000-00000000000g") is None
    assert uuid_from_text("") is None
    # 33 hex-цифры (на одну больше 32) тоже отклоняются.
    assert uuid_from_text("0" * 33) is None


def test_uuid_text_matches_python_stdlib():
    u = uuid_from_text(CANON)
    assert u is not None
    assert uuid_text(u) == CANON
    # Согласованность со стандартной библиотекой Python.
    assert uuid_text(u) == str(py_uuid.UUID(hex=CANON))


# ── класс UUID ─────────────────────────────────────────────────────────────
def test_from_str_to_str_round_trip():
    u = UUID.from_str(CANON)
    assert u.to_str() == CANON
    assert str(u) == CANON
    # Дефисы не обязательны.
    assert UUID.from_str(CANON.replace("-", "")) == u


def test_from_bytes_to_bytes_round_trip():
    u = UUID.from_str(CANON)
    assert len(u.to_bytes()) == 16
    assert u.to_bytes() == py_uuid.UUID(hex=CANON).bytes
    assert UUID.from_bytes(u.to_bytes()) == u


def test_from_int_to_int_round_trip():
    u = UUID.from_str(CANON)
    n = u.to_int()
    assert n == int(CANON.replace("-", ""), 16)
    assert UUID.from_int(n) == u
    # Отрицательные/переполненные int обрезаются до 128 бит, как u128.
    assert UUID.from_int(n).to_int() == n


def test_version_and_variant_of_v4():
    u = UUID.from_str(CANON)
    assert u.version() == 4
    assert u.variant() == py_uuid.RFC_4122


def test_msb_lsb_are_signed_longs():
    # 0x550e8400... / 0xe29b41d4...: старший hex > 7 → знаковый long < 0.
    u = UUID.from_str(CANON)
    assert u.msb == 0x550E8400E29B41D4
    assert u.lsb == 0xA716446655440000 - (1 << 64)


def test_from_str_invalid_raises():
    with pytest.raises(ValueError):
        UUID.from_str("not-a-uuid")
    with pytest.raises(ValueError):
        UUID.from_str("")
    with pytest.raises(ValueError):
        UUID.from_str("00000000-0000-0000-0000-00000000000g")
    with pytest.raises(ValueError):
        UUID.from_bytes(b"\x00" * 15)
