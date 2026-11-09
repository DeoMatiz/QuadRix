# Порт horizon-protocol/src/ids.rs + таблиц ID пакетов старых версий из
# adapter/v1_21_10.rs, adapter/v1_21_11.rs, adapter/v26_1_2.rs и adapter/v26_2.rs.
#
# ids.rs — это таблицы ID пакетов для протокола 777 (26.3) по состояниям
# соединения (State) и направлениям (Direction). Для каждой пары
# (State, Direction) есть словарь ``id -> имя``; имя хранится ровно так,
# как его пишет Rust (включая имена вида ``debug/block_value``).
#
# adapter/v*_ids.rs — это НЕ ID пакетов, а ремапы ID реестров
# (block_state, item, entity_type, ...). Сюда они не входят.
# ID пакетов старых версий лежат в adapter/v1_21_10.rs и соседних файлах:
# там для каждого старого ID записан ID в 26.3 (clientbound) либо для
# каждого ID 26.3 записан ID старой версии (serverbound).
#
# Сознательно НЕ портируется:
#   * packets/*.rs — декодирование/кодирование самих пакетов;
#   * adapter/*_ids.rs — ремапы реестров (другая задача).

from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "State",
    "Direction",
    "PacketIdAdapter",
    "HANDSHAKE_SERVERBOUND",
    "STATUS_CLIENTBOUND",
    "STATUS_SERVERBOUND",
    "LOGIN_CLIENTBOUND",
    "LOGIN_SERVERBOUND",
    "CONFIGURATION_CLIENTBOUND",
    "CONFIGURATION_SERVERBOUND",
    "PLAY_CLIENTBOUND",
    "PLAY_SERVERBOUND",
    "NAMES",
    "TABLES",
    "REVERSE",
    "handshake",
    "status",
    "login",
    "configuration",
    "play",
    "name",
    "name_of",
    "id_of",
    "v1_21_10",
    "v1_21_11",
    "v26_1_2",
    "v26_2",
    "ADAPTERS",
]


class State(Enum):
    """Состояния протокола (ConnectionProtocol в vanilla / State в Rust)."""

    HANDSHAKE = "handshake"
    STATUS = "status"
    LOGIN = "login"
    CONFIGURATION = "configuration"
    PLAY = "play"


class Direction(Enum):
    """Направление пакета (PacketFlow в vanilla / Direction в Rust)."""

    CLIENTBOUND = "clientbound"
    SERVERBOUND = "serverbound"


# ── Таблицы ID пакетов 26.3 (ids.rs) ──────────────────────────────────

HANDSHAKE_SERVERBOUND: Dict[int, str] = {
    0: "intention",
}

STATUS_CLIENTBOUND: Dict[int, str] = {
    0: "status_response",
    1: "pong_response",
}

STATUS_SERVERBOUND: Dict[int, str] = {
    0: "status_request",
    1: "ping_request",
}

LOGIN_CLIENTBOUND: Dict[int, str] = {
    0: "login_disconnect",
    1: "hello",
    2: "login_finished",
    3: "login_compression",
    4: "custom_query",
    5: "cookie_request",
}

LOGIN_SERVERBOUND: Dict[int, str] = {
    0: "hello",
    1: "key",
    2: "custom_query_answer",
    3: "login_acknowledged",
    4: "cookie_response",
}

CONFIGURATION_CLIENTBOUND: Dict[int, str] = {
    0: "cookie_request",
    1: "custom_payload",
    2: "disconnect",
    3: "finish_configuration",
    4: "keep_alive",
    5: "ping",
    6: "reset_chat",
    7: "registry_data",
    8: "resource_pack_pop",
    9: "resource_pack_push",
    10: "post_effects",
    11: "store_cookie",
    12: "transfer",
    13: "update_enabled_features",
    14: "update_tags",
    15: "select_known_packs",
    16: "custom_report_details",
    17: "server_links",
    18: "clear_dialog",
    19: "show_dialog",
    20: "code_of_conduct",
}

CONFIGURATION_SERVERBOUND: Dict[int, str] = {
    0: "client_information",
    1: "cookie_response",
    2: "custom_payload",
    3: "finish_configuration",
    4: "keep_alive",
    5: "pong",
    6: "resource_pack",
    7: "select_known_packs",
    8: "custom_click_action",
    9: "accept_code_of_conduct",
}

PLAY_CLIENTBOUND: Dict[int, str] = {
    0: "bundle_delimiter",
    1: "add_entity",
    2: "animate",
    3: "award_stats",
    4: "block_changed_ack",
    5: "block_destruction",
    6: "block_entity_data",
    7: "block_event",
    8: "block_update",
    9: "boss_event",
    10: "change_difficulty",
    11: "chunk_batch_finished",
    12: "chunk_batch_start",
    13: "chunks_biomes",
    14: "clear_titles",
    15: "command_suggestions",
    16: "commands",
    17: "container_close",
    18: "container_set_content",
    19: "container_set_data",
    20: "container_set_slot",
    21: "cookie_request",
    22: "cooldown",
    23: "custom_chat_completions",
    24: "custom_payload",
    25: "damage_event",
    26: "debug/block_value",
    27: "debug/chunk_value",
    28: "debug/entity_value",
    29: "debug/event",
    30: "debug_sample",
    31: "delete_chat",
    32: "disconnect",
    33: "disguised_chat",
    34: "entity_event",
    35: "entity_position_sync",
    36: "explode",
    37: "add_transient_block",
    38: "forget_level_chunk",
    39: "game_event",
    40: "game_rule_values",
    41: "game_test_highlight_pos",
    42: "mount_screen_open",
    43: "hurt_animation",
    44: "initialize_border",
    45: "keep_alive",
    46: "level_chunk_with_light",
    47: "level_event",
    48: "level_particles",
    49: "light_update",
    50: "login",
    51: "low_disk_space_warning",
    52: "map_item_data",
    53: "merchant_offers",
    54: "move_entity_pos",
    55: "move_entity_pos_rot",
    56: "move_minecart_along_track",
    57: "move_entity_rot",
    58: "move_vehicle",
    59: "open_book",
    60: "open_screen",
    61: "open_sign_editor",
    62: "ping",
    63: "pong_response",
    64: "place_ghost_recipe",
    65: "player_abilities",
    66: "player_chat",
    67: "player_combat_end",
    68: "player_combat_enter",
    69: "player_combat_kill",
    70: "player_info_remove",
    71: "player_info_update",
    72: "player_look_at",
    73: "player_position",
    74: "player_rotation",
    75: "recipe_book_add",
    76: "recipe_book_remove",
    77: "recipe_book_settings",
    78: "remove_entities",
    79: "remove_mob_effect",
    80: "reset_score",
    81: "resource_pack_pop",
    82: "resource_pack_push",
    83: "post_effects",
    84: "respawn",
    85: "rotate_head",
    86: "section_blocks_update",
    87: "select_advancements_tab",
    88: "server_data",
    89: "set_action_bar_text",
    90: "set_border_center",
    91: "set_border_lerp_size",
    92: "set_border_size",
    93: "set_border_warning_delay",
    94: "set_border_warning_distance",
    95: "set_camera",
    96: "set_chunk_cache_center",
    97: "set_chunk_cache_radius",
    98: "set_cursor_item",
    99: "set_default_spawn_position",
    100: "set_display_objective",
    101: "set_entity_data",
    102: "set_entity_link",
    103: "set_entity_motion",
    104: "set_equipment",
    105: "set_experience",
    106: "set_health",
    107: "set_held_slot",
    108: "set_objective",
    109: "set_passengers",
    110: "set_player_inventory",
    111: "set_player_team",
    112: "set_score",
    113: "set_simulation_distance",
    114: "set_subtitle_text",
    115: "set_time",
    116: "set_title_text",
    117: "set_titles_animation",
    118: "sound_entity",
    119: "sound",
    120: "start_configuration",
    121: "stop_sound",
    122: "store_cookie",
    123: "swing_animation",
    124: "system_chat",
    125: "tab_list",
    126: "tag_query",
    127: "take_item_entity",
    128: "teleport_entity",
    129: "test_instance_block_status",
    130: "ticking_state",
    131: "ticking_step",
    132: "transfer",
    133: "update_advancements",
    134: "update_attributes",
    135: "update_mob_effect",
    136: "update_recipes",
    137: "update_tags",
    138: "projectile_power",
    139: "custom_report_details",
    140: "server_links",
    141: "waypoint",
    142: "clear_dialog",
    143: "show_dialog",
}

PLAY_SERVERBOUND: Dict[int, str] = {
    0: "accept_teleportation",
    1: "attack",
    2: "block_entity_tag_query",
    3: "bundle_item_selected",
    4: "change_difficulty",
    5: "change_game_mode",
    6: "chat_ack",
    7: "chat_command",
    8: "chat_command_signed",
    9: "chat",
    10: "chat_session_update",
    11: "chunk_batch_received",
    12: "client_command",
    13: "client_tick_end",
    14: "client_information",
    15: "command_suggestion",
    16: "configuration_acknowledged",
    17: "container_button_click",
    18: "container_click",
    19: "container_close",
    20: "container_slot_state_changed",
    21: "cookie_response",
    22: "custom_payload",
    23: "debug_subscription_request",
    24: "edit_book",
    25: "entity_tag_query",
    26: "interact",
    27: "jigsaw_generate",
    28: "keep_alive",
    29: "lock_difficulty",
    30: "move_player_pos",
    31: "move_player_pos_rot",
    32: "move_player_rot",
    33: "move_player_status_only",
    34: "move_vehicle",
    35: "paddle_boat",
    36: "pick_item_from_block",
    37: "pick_item_from_entity",
    38: "ping_request",
    39: "place_recipe",
    40: "player_abilities",
    41: "player_action",
    42: "player_command",
    43: "player_input",
    44: "player_loaded",
    45: "pong",
    46: "punch",
    47: "recipe_book_change_settings",
    48: "recipe_book_seen_recipe",
    49: "rename_item",
    50: "resource_pack",
    51: "seen_advancements",
    52: "select_trade",
    53: "set_beacon",
    54: "set_carried_item",
    55: "set_command_block",
    56: "set_command_minecart",
    57: "set_creative_mode_slot",
    58: "set_game_rule",
    59: "set_jigsaw_block",
    60: "set_structure_block",
    61: "set_test_block",
    62: "sign_update",
    63: "spectator_action",
    64: "teleport_to_entity",
    65: "test_instance_block_action",
    66: "use_item_on",
    67: "use_item",
    68: "custom_click_action",
}


TABLES: Dict[Tuple[State, Direction], Dict[int, str]] = {
    (State.HANDSHAKE, Direction.SERVERBOUND): HANDSHAKE_SERVERBOUND,
    (State.STATUS, Direction.CLIENTBOUND): STATUS_CLIENTBOUND,
    (State.STATUS, Direction.SERVERBOUND): STATUS_SERVERBOUND,
    (State.LOGIN, Direction.CLIENTBOUND): LOGIN_CLIENTBOUND,
    (State.LOGIN, Direction.SERVERBOUND): LOGIN_SERVERBOUND,
    (State.CONFIGURATION, Direction.CLIENTBOUND): CONFIGURATION_CLIENTBOUND,
    (State.CONFIGURATION, Direction.SERVERBOUND): CONFIGURATION_SERVERBOUND,
    (State.PLAY, Direction.CLIENTBOUND): PLAY_CLIENTBOUND,
    (State.PLAY, Direction.SERVERBOUND): PLAY_SERVERBOUND,
}

#: Имена пакетов по ID, как ``NAMES`` в Rust (индекс = ID).
NAMES: Dict[Tuple[State, Direction], Tuple[str, ...]] = {
    key: tuple(table[i] for i in sorted(table)) for key, table in TABLES.items()
}

#: Обратная таблица: (State, Direction, имя) -> ID.
REVERSE: Dict[Tuple[State, Direction], Dict[str, int]] = {
    key: {packet_name: packet_id for packet_id, packet_name in table.items()}
    for key, table in TABLES.items()
}


def _packet_namespace(table: Mapping[int, str]) -> SimpleNamespace:
    """Собрать модуль в стиле Rust: ``NAMES`` плюс константы по именам.

    Rust объявляет ``pub const BUNDLE_DELIMITER: i32 = 0;`` и
    ``pub const NAMES: &[&str]``. Здесь те же константы создаются из
    таблицы, чтобы ID и имена не могли разойтись.
    """
    namespace = SimpleNamespace(NAMES=tuple(table[i] for i in sorted(table)))
    for packet_id, packet_name in table.items():
        setattr(namespace, packet_name.upper().replace("/", "_"), packet_id)
    return namespace


# Те же вложенные модули, что и в Rust: handshake::serverbound, play::clientbound, ...
handshake = SimpleNamespace(serverbound=_packet_namespace(HANDSHAKE_SERVERBOUND))
status = SimpleNamespace(
    clientbound=_packet_namespace(STATUS_CLIENTBOUND),
    serverbound=_packet_namespace(STATUS_SERVERBOUND),
)
login = SimpleNamespace(
    clientbound=_packet_namespace(LOGIN_CLIENTBOUND),
    serverbound=_packet_namespace(LOGIN_SERVERBOUND),
)
configuration = SimpleNamespace(
    clientbound=_packet_namespace(CONFIGURATION_CLIENTBOUND),
    serverbound=_packet_namespace(CONFIGURATION_SERVERBOUND),
)
play = SimpleNamespace(
    clientbound=_packet_namespace(PLAY_CLIENTBOUND),
    serverbound=_packet_namespace(PLAY_SERVERBOUND),
)


def name(state: State, direction: Direction, packet_id: int) -> Optional[str]:
    """Имя пакета по ID или ``None`` — точный порт ``ids::name``.

    Для пары (State, Direction), которой в Rust соответствует ``&[]``
    (например, Handshake + Clientbound), возвращается ``None``.
    Отрицательный ID тоже даёт ``None``, как ``usize::try_from`` в Rust.
    """
    names = NAMES.get((state, direction))
    if names is None or packet_id < 0 or packet_id >= len(names):
        return None
    return names[packet_id]


def name_of(
    packet_id: int,
    state: State = State.PLAY,
    direction: Direction = Direction.CLIENTBOUND,
) -> str:
    """Имя пакета по ID; неизвестный ID — ``KeyError``.

    По умолчанию используется Play + Clientbound, потому что это самая
    частая пара. Как в Rust, отсутствие записи — это ошибка, а не
    пустая строка.
    """
    packet_name = name(state, direction, packet_id)
    if packet_name is None:
        raise KeyError(
            f"[QuadRix] нет пакета с id={packet_id} "
            f"для state={state.value} direction={direction.value}"
        )
    return packet_name


def id_of(
    packet_name: str,
    state: State = State.PLAY,
    direction: Direction = Direction.CLIENTBOUND,
) -> int:
    """ID пакета по имени; неизвестное имя — ``KeyError``."""
    reverse = REVERSE.get((state, direction))
    if reverse is None or packet_name not in reverse:
        raise KeyError(
            f"[QuadRix] нет пакета с именем {packet_name!r} "
            f"для state={state.value} direction={direction.value}"
        )
    return reverse[packet_name]


# ── ID пакетов старых версий (adapter/v*.rs) ──────────────────────────
#
# ``clientbound``: для каждого ID, который присылает сервер старой версии,
#   записан ID того же пакета в 26.3 (None — пакета нет в 26.3).
# ``serverbound``: для каждого ID 26.3, который шлёт Horizon, записан ID,
#   известный серверу старой версии (None — старая версия его не знает).


class PacketIdAdapter:
    """Таблица перевода ID пакетов одной старой версии в 26.3 и обратно."""

    def __init__(
        self,
        protocol: int,
        version_name: str,
        clientbound: Mapping[State, Tuple[Optional[int], ...]],
        serverbound: Mapping[State, Tuple[Optional[int], ...]],
    ) -> None:
        self.protocol = protocol
        self.name = version_name
        self._clientbound = dict(clientbound)
        self._serverbound = dict(serverbound)

    def clientbound(self, state: State) -> Tuple[Optional[int], ...]:
        """Для каждого ID старой версии — ID пакета в 26.3."""
        return self._clientbound[state]

    def serverbound(self, state: State) -> Tuple[Optional[int], ...]:
        """Для каждого ID 26.3 — ID пакета в старой версии."""
        return self._serverbound[state]


# protocol 773, 1.21.10
v1_21_10 = PacketIdAdapter(
    773,
    "1.21.10",
    {
        State.HANDSHAKE: (),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4, 5),
        State.CONFIGURATION: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        ),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 38, 39, 41, 42, 43, 44, 45, 46, 47, 48, 49,
            50, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62,
            63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
            75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87,
            88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
            100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
            112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 124,
            125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136,
            137, 138, 139, 140, 141, 142, 143,
        ),
    },
    {
        State.HANDSHAKE: (0,),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4),
        State.CONFIGURATION: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        State.PLAY: (
            0, None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
            11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
            23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
            35, 36, 37, 38, 39, 40, 41, 42, 43, 44, None, 45,
            46, 47, 48, 49, 50, 51, 52, 53, 54, 55, None, 56,
            57, 58, 59, None, 61, 62, 63, 64, 65,
        ),
    },
)

# protocol 774, 1.21.11
v1_21_11 = PacketIdAdapter(
    774,
    "1.21.11",
    {
        State.HANDSHAKE: (),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4, 5),
        State.CONFIGURATION: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        ),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 38, 39, 41, 42, 43, 44, 45, 46, 47, 48, 49,
            50, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62,
            63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74,
            75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87,
            88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
            100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
            112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 124,
            125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136,
            137, 138, 139, 140, 141, 142, 143,
        ),
    },
    {
        State.HANDSHAKE: (0,),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4),
        State.CONFIGURATION: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        State.PLAY: (
            0, None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
            11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
            23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
            35, 36, 37, 38, 39, 40, 41, 42, 43, 44, None, 45,
            46, 47, 48, 49, 50, 51, 52, 53, 54, 55, None, 56,
            57, 58, 59, None, 61, 62, 63, 64, 65,
        ),
    },
)

# protocol 775, 26.1.2
v26_1_2 = PacketIdAdapter(
    775,
    "26.1.2",
    {
        State.HANDSHAKE: (),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4, 5),
        State.CONFIGURATION: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        ),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
            49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60,
            61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72,
            73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85,
            86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97,
            98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
            110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
            122, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134,
            135, 136, 137, 138, 139, 140, 141, 142, 143,
        ),
    },
    {
        State.HANDSHAKE: (0,),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4),
        State.CONFIGURATION: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 37, 38, 39, 40, 41, 42, 43, 44, 45, None, 46,
            47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
            59, 60, 61, None, 64, 65, 66, 67, 68,
        ),
    },
)

# protocol 776, 26.2
v26_2 = PacketIdAdapter(
    776,
    "26.2",
    {
        State.HANDSHAKE: (),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4, 5),
        State.CONFIGURATION: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        ),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
            49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60,
            61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72,
            73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85,
            86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97,
            98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
            110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
            122, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134,
            135, 136, 137, 138, 139, 140, 141, 142, 143,
        ),
    },
    {
        State.HANDSHAKE: (0,),
        State.STATUS: (0, 1),
        State.LOGIN: (0, 1, 2, 3, 4),
        State.CONFIGURATION: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        State.PLAY: (
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
            12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
            36, 37, 38, 39, 40, 41, 42, 43, 44, 45, None, 46,
            47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
            59, 60, 61, 62, 64, 65, 66, 67, 68,
        ),
    },
)

#: Адаптеры по имени версии.
ADAPTERS: Dict[str, PacketIdAdapter] = {
    adapter.name: adapter for adapter in (v1_21_10, v1_21_11, v26_1_2, v26_2)
}
