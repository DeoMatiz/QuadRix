#!/usr/bin/env python3
"""Тесты quadrix/protocol/ids.py.

Источник — horizon-protocol/src/ids.rs (ID пакетов 26.3) и
adapter/v1_21_10.rs, adapter/v1_21_11.rs, adapter/v26_1_2.rs,
adapter/v26_2.rs (ID пакетов старых версий).

ids.rs не читает .local: это статические таблицы, поэтому тестов с
реальными данными .local здесь нет. Значения взяты из Rust дословно.
"""

from __future__ import annotations

import pytest

from quadrix.protocol.ids import (
    ADAPTERS,
    CONFIGURATION_CLIENTBOUND,
    CONFIGURATION_SERVERBOUND,
    Direction,
    HANDSHAKE_SERVERBOUND,
    LOGIN_CLIENTBOUND,
    LOGIN_SERVERBOUND,
    NAMES,
    PLAY_CLIENTBOUND,
    PLAY_SERVERBOUND,
    REVERSE,
    State,
    TABLES,
    configuration,
    handshake,
    id_of,
    login,
    name,
    name_of,
    status,
    v1_21_10,
    v1_21_11,
    v26_1_2,
    v26_2,
)


# Вспомогательная проверка: полный round-trip id -> name -> id.
def _round_trip(state, direction, table):
    for packet_id, packet_name in table.items():
        assert name_of(packet_id, state, direction) == packet_name
        assert id_of(packet_name, state, direction) == packet_id


def test_play_clientbound_known_ids():
    """0x00 bundle_delimiter, 0x01 add_entity и ещё несколько из ids.rs."""
    assert PLAY_CLIENTBOUND[0x00] == "bundle_delimiter"
    assert PLAY_CLIENTBOUND[0x01] == "add_entity"
    assert PLAY_CLIENTBOUND[0x02] == "animate"
    assert PLAY_CLIENTBOUND[0x32] == "login"  # 50
    assert PLAY_CLIENTBOUND[0x8F] == "show_dialog"  # 143
    assert name_of(0x00) == "bundle_delimiter"
    assert name_of(0x01) == "add_entity"
    assert id_of("bundle_delimiter") == 0
    assert id_of("add_entity") == 1

    # Имена с косой чертой сохраняются как в Rust: debug/block_value.
    assert PLAY_CLIENTBOUND[26] == "debug/block_value"
    assert id_of("debug/block_value") == 26
    # У play clientbound 144 записи (0..143).
    assert len(PLAY_CLIENTBOUND) == 144
    assert len(PLAY_CLIENTBOUND) > 100


def test_play_serverbound_known_ids():
    """Play serverbound тоже сверить с ids.rs."""
    assert PLAY_SERVERBOUND[0x00] == "accept_teleportation"
    assert PLAY_SERVERBOUND[0x01] == "attack"
    assert PLAY_SERVERBOUND[0x09] == "chat"  # 9
    assert PLAY_SERVERBOUND[0x1C] == "keep_alive"  # 28
    assert PLAY_SERVERBOUND[0x44] == "custom_click_action"  # 68
    assert name_of(28, State.PLAY, Direction.SERVERBOUND) == "keep_alive"
    assert id_of("custom_click_action", State.PLAY, Direction.SERVERBOUND) == 68


def test_handshake_and_status():
    """Handshake: 0 = intention (serverbound). Status — оба направления."""
    assert HANDSHAKE_SERVERBOUND == {0: "intention"}
    assert handshake.serverbound.INTENTION == 0
    assert handshake.serverbound.NAMES == ("intention",)

    assert name_of(0, State.HANDSHAKE, Direction.SERVERBOUND) == "intention"
    assert name_of(0, State.STATUS, Direction.CLIENTBOUND) == "status_response"
    assert name_of(0, State.STATUS, Direction.SERVERBOUND) == "status_request"
    assert id_of("status_response", State.STATUS, Direction.CLIENTBOUND) == 0
    assert id_of("ping_request", State.STATUS, Direction.SERVERBOUND) == 1
    assert status.clientbound.PONG_RESPONSE == 1
    assert status.serverbound.PING_REQUEST == 1


def test_login_matches_rust_not_the_reversed_example():
    """В Rust login clientbound 0 = login_disconnect, 2 = login_finished.

    В задании пример был перепутан местами; тест фиксирует ids.rs:
    serverbound 0 = hello, 2 = custom_query_answer.
    """
    assert LOGIN_CLIENTBOUND[0] == "login_disconnect"
    assert LOGIN_CLIENTBOUND[2] == "login_finished"
    assert LOGIN_SERVERBOUND[0] == "hello"
    assert LOGIN_SERVERBOUND[2] == "custom_query_answer"
    assert login.clientbound.LOGIN_FINISHED == 2
    assert login.serverbound.HELLO == 0


def test_configuration_matches_rust():
    """Configuration: clientbound 0 = cookie_request, serverbound 0 = client_information."""
    assert CONFIGURATION_CLIENTBOUND[0] == "cookie_request"
    assert CONFIGURATION_SERVERBOUND[0] == "client_information"
    assert configuration.clientbound.COOKIE_REQUEST == 0
    assert configuration.serverbound.CLIENT_INFORMATION == 0
    assert configuration.clientbound.CODE_OF_CONDUCT == 20
    assert configuration.serverbound.ACCEPT_CODE_OF_CONDUCT == 9


def test_unknown_ids_and_names_raise_key_error():
    """Неизвестный ID/имя — KeyError; name() как в Rust возвращает None."""
    assert name(State.HANDSHAKE, Direction.SERVERBOUND, 1) is None
    assert name(State.HANDSHAKE, Direction.SERVERBOUND, -1) is None
    # У Handshake нет clientbound-таблицы: Rust отдаёт &[].
    assert name(State.HANDSHAKE, Direction.CLIENTBOUND, 0) is None

    with pytest.raises(KeyError):
        name_of(1, State.HANDSHAKE, Direction.SERVERBOUND)
    with pytest.raises(KeyError):
        name_of(144)
    with pytest.raises(KeyError):
        name_of(0, State.HANDSHAKE, Direction.CLIENTBOUND)
    with pytest.raises(KeyError):
        id_of("no_such_packet")
    with pytest.raises(KeyError):
        id_of("intention", State.HANDSHAKE, Direction.CLIENTBOUND)


def test_every_table_round_trips_and_names_are_indexed_by_id():
    """name_of(id_of(x)) == x для всех таблиц и NAMES[i] == id i."""
    for (state, direction), table in TABLES.items():
        _round_trip(state, direction, table)
        assert NAMES[(state, direction)] == tuple(table[i] for i in range(len(table)))
        assert REVERSE[(state, direction)] == {
            packet_name: packet_id for packet_id, packet_name in table.items()
        }


def test_version_adapter_tables():
    """ID старых версий из adapter/v*.rs: длины и контрольные точки."""
    assert set(ADAPTERS) == {"1.21.10", "1.21.11", "26.1.2", "26.2"}
    assert (v1_21_10.protocol, v1_21_10.name) == (773, "1.21.10")
    assert (v1_21_11.protocol, v1_21_11.name) == (774, "1.21.11")
    assert (v26_1_2.protocol, v26_1_2.name) == (775, "26.1.2")
    assert (v26_2.protocol, v26_2.name) == (776, "26.2")

    # clientbound: 139 записей у play в 1.21.10/1.21.11 и 141 в 26.1.2/26.2;
    # 20 у configuration (нет старого ID 10).
    for adapter in (v1_21_10, v1_21_11):
        assert len(adapter.clientbound(State.PLAY)) == 139
    for adapter in (v26_1_2, v26_2):
        assert len(adapter.clientbound(State.PLAY)) == 141
    for adapter in (v1_21_10, v1_21_11, v26_1_2, v26_2):
        assert len(adapter.clientbound(State.CONFIGURATION)) == 20
        assert adapter.clientbound(State.HANDSHAKE) == ()

    # 1.21.10 play clientbound: старый 37 -> pinned 38 (пропущен pinned 37).
    assert v1_21_10.clientbound(State.PLAY)[36] == 36
    assert v1_21_10.clientbound(State.PLAY)[37] == 38
    assert v1_21_10.clientbound(State.PLAY)[38] == 39
    # configuration clientbound: старый 10 -> pinned 11 (пропущен 10).
    assert v1_21_10.clientbound(State.CONFIGURATION)[10] == 11

    # serverbound всегда 69 записей (по одной на pinned ID 0..68).
    for adapter in (v1_21_10, v1_21_11, v26_1_2, v26_2):
        assert len(adapter.serverbound(State.PLAY)) == 69

    assert v1_21_10.serverbound(State.PLAY)[1] is None
    assert v26_1_2.serverbound(State.PLAY)[63] is None
    assert v26_2.serverbound(State.PLAY)[63] == 62
    assert v26_2.serverbound(State.PLAY)[64] == 64
