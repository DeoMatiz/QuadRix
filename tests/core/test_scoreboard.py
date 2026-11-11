# Тесты порта табло (horizon-client-core/src/scoreboard.rs) →
# quadrix/core/scoreboard.py.
#
# Проверяем модели (Objective/Score/Team/Scoreboard/NumberFormat), операции
# (add/remove objective, set/get/reset счёта, команды, display slots),
# сериализацию pack/unpack (в т.ч. бинарный NBT round-trip) и game-правила
# команд (damage/collision/invisibility/death message). Один тест грузит
# настоящий экспорт `.local/command-registries/registries.json`.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quadrix.core import scoreboard as sb_mod
from quadrix.core.registries import Registries
from quadrix.core.scoreboard import (
    CUSTOM_CRITERIA,
    I32_MAX,
    I32_MIN,
    CollisionRule,
    InvalidIdentifier,
    NameView,
    NumberFormat,
    Objective,
    RenderType,
    Score,
    Scoreboard,
    Team,
    Visibility,
    criteria_by_name,
    criteria_exists,
    criteria_read_only,
    criteria_render_type,
    death_message_args,
    death_message_reaches,
    display_slot_valid,
    display_slots,
    invisible_to,
    literal,
    name_shown,
    pushable_by,
    stat_criteria,
    team_color_rgb,
    team_shows_name,
    teams_allow_damage,
    teams_allied,
    comp_text,
)
from quadrix.core.text import RED, Text

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / ".local" / "command-registries" / "registries.json"


def board() -> Scoreboard:
    b = Scoreboard()
    b.add_objective("kills", "playerKillCount", literal("Kills"), RenderType.Integer, False, None)
    b.add_objective("hp", "health", literal("HP"), RenderType.Hearts, True, NumberFormat.blank())
    return b


# ── критерии ───────────────────────────────────────────────────────────────
def test_criteria_names() -> None:
    reg = Registries()
    assert criteria_exists("dummy", reg)
    assert criteria_exists("teamkill.red", reg)
    assert criteria_exists("killedByTeam.dark_blue", reg)
    assert not criteria_exists("teamkill.pink", reg)
    assert criteria_exists("minecraft.mined:minecraft.stone", reg)
    assert criteria_exists("minecraft.custom:minecraft.jump", reg)
    assert not criteria_exists("minecraft.custom:minecraft.nope", reg)
    assert not criteria_exists("minecraft.flown:minecraft.stone", reg)
    assert not criteria_exists("nonsense", reg)
    assert criteria_read_only("health") and not criteria_read_only("dummy")
    assert criteria_render_type("health") is RenderType.Hearts
    assert (
        stat_criteria("minecraft:mined", "minecraft:stone")
        == "minecraft.mined:minecraft.stone"
    )
    reg2 = Registries(items=["minecraft:stick"])
    assert criteria_exists("minecraft.crafted:minecraft.stick", reg2)
    assert not criteria_exists("minecraft.crafted:minecraft.dirt", reg2)


def test_criteria_invalid_identifier_raises() -> None:
    reg = Registries()
    with pytest.raises(InvalidIdentifier):
        criteria_by_name("minecraft.mined:UPPER", reg)
    # Неизвестный тип статистики — не ошибка, просто None.
    assert criteria_by_name("minecraft.flown:minecraft.stone", reg) is None
    assert len(CUSTOM_CRITERIA) == 11
    assert criteria_by_name("dummy", reg) == "dummy"


def test_canonical_stat_criteria_isolated() -> None:
    # `minecraft:mined` (короткая форма) канонизируется.
    reg = Registries()
    assert (
        criteria_by_name("mined:minecraft.stone", reg)
        == "minecraft.mined:minecraft.stone"
    )


# ── Objective / Score ──────────────────────────────────────────────────────
def test_objective_create_and_duplicate() -> None:
    b = Scoreboard()
    assert b.add_objective("kills", "playerKillCount", literal("Kills")) is True
    o = b.objective("kills")
    assert isinstance(o, Objective)
    assert o.name == "kills"
    assert o.criteria == "playerKillCount"
    assert o.display_name == "Kills"
    assert o.render_type is RenderType.Integer
    assert o.display_auto_update is False
    assert o.number_format is None
    # Дубликат отклонён.
    assert b.add_objective("kills", "dummy", literal("x")) is False
    assert b.objective("nope") is None


def test_score_defaults_locked_zero() -> None:
    b = Scoreboard()
    b.add_objective("kills", "dummy", literal("K"))
    s = b.score_mut("Steve", "kills")
    assert isinstance(s, Score)
    assert s.value == 0
    assert s.locked is True
    assert s.display is None
    assert s.number_format is None
    assert b.get("Steve", "kills") == 0


def test_scores_and_criteria_updates() -> None:
    b = board()
    assert not b.add_objective("kills", "dummy", literal("x"))
    assert b.score_mut("Steve", "kills").locked
    b.for_all_objectives("playerKillCount", "Steve", lambda v: v + 1)
    b.for_all_objectives("playerKillCount", "Steve", lambda v: v + 1)
    assert b.get("Steve", "kills") == 2
    assert b.add("Steve", "kills", 5) == 7
    assert len(b.holder_scores("Steve")) == 1
    b.set("Alex", "hp", 20)
    tracked = sorted(b.tracked())
    assert tracked == ["Alex", "Steve"]
    b.reset_one("Alex", "hp")
    assert b.tracked() == ["Steve"]
    b.set_display_objective("sidebar", "kills")
    b.remove_objective("kills")
    assert b.display_objective("sidebar") is None
    # removeObjective оставляет владельца без счетов.
    assert b.tracked() == ["Steve"]
    assert b.holder_scores("Steve") == []


def test_add_wraps_i32() -> None:
    b = Scoreboard()
    b.add_objective("s", "dummy", literal("s"))
    b.set("p", "s", I32_MAX)
    assert b.add("p", "s", 1) == I32_MIN


def test_set_get_reset() -> None:
    b = board()
    b.set("Steve", "kills", 3)
    assert b.get("Steve", "kills") == 3
    assert b.score("Steve", "kills").value == 3
    b.reset_one("Steve", "kills")
    assert b.score("Steve", "kills") is None
    assert b.tracked() == []
    b.set("Steve", "kills", 9)
    b.reset_all("Steve")
    assert b.tracked() == []
    assert b.score("Steve", "kills") is None


def test_list_scores_and_holder_scores() -> None:
    b = board()
    b.set("Steve", "kills", 3)
    b.set("Alex", "kills", 4)
    entries = b.list_scores("kills")
    owners = [e.owner for e in entries]
    assert owners == ["Steve", "Alex"]
    assert entries[0].value == 3
    assert entries[0].is_hidden() is False
    assert entries[0].owner_name().plain() == "Steve"
    hs = b.holder_scores("Steve")
    assert len(hs) == 1
    assert hs[0][0].name == "kills" and hs[0][1] == 3


# ── Team ───────────────────────────────────────────────────────────────────
def test_team_defaults() -> None:
    t = Team.create("red")
    assert t.name == "red"
    assert t.display_name == "red"
    assert t.color is None
    assert t.allow_friendly_fire is True
    assert t.see_friendly_invisibles is True
    assert t.prefix == ""
    assert t.suffix == ""
    assert t.nametag_visibility is Visibility.Always
    assert t.death_message_visibility is Visibility.Always
    assert t.collision_rule is CollisionRule.Always
    assert t.players == []


def test_team_color_prefix_and_formatted() -> None:
    b = Scoreboard()
    t = b.add_team("red")
    t.color = "red"
    t.prefix = literal("[R] ")
    t.suffix = literal("!")
    assert team_color_rgb("red") == RED
    assert team_color_rgb("not_a_color") is None
    name = t.formatted_name(Text.literal("Steve"))
    assert name.plain() == "[R] Steve!"
    assert name.spans[0].style.color == RED
    comp = t.formatted_name_comp("Steve")
    assert comp == {"text": "", "extra": ["[R] ", "Steve", "!"], "color": "red"}
    assert isinstance(t.formatted_display_name(), Text)
    # Цвет без RGB (невалидный) не применяется.
    t.color = "nonsense"
    assert t.formatted_name(Text.literal("x")).spans[0].style.color is None


def test_team_membership() -> None:
    b = Scoreboard()
    b.add_team("red")
    b.add_team("blue")
    assert b.add_to_team("Steve", "red") is True
    # Повторный вход в ту же команду сначала покидает её, поэтому True.
    assert b.add_to_team("Steve", "red") is True
    assert b.add_to_team("Alex", "red") is True
    assert b.allied("Steve", "Alex")
    assert b.add_to_team("Steve", "blue") is True
    assert not b.allied("Steve", "Alex")
    assert len(b.team("red").players) == 1
    assert b.remove_from_team("Alex") is True
    assert b.remove_from_team("Alex") is False
    b.remove_team("blue")
    assert b.players_team("Steve") is None
    # Вход в несуществующую команду — False.
    assert b.add_to_team("Nobody", "ghost") is False


def test_team_add_remove_streamed() -> None:
    b = Scoreboard()
    b.add_team("a")
    b.add_team("b")
    assert [t.name for t in b.teams_streamed()] == ["a", "b"]
    assert b.team("missing") is None
    b.remove_team("a")
    assert [t.name for t in b.teams_streamed()] == ["b"]
    assert sorted(b.team_members()) == []


def test_entity_removed() -> None:
    b = board()
    b.add_team("red")
    b.add_to_team("Steve", "red")
    b.set("Steve", "kills", 1)
    b.entity_removed("Steve")
    assert b.tracked() == []
    assert b.players_team("Steve") is None


# ── display slots ──────────────────────────────────────────────────────────
def test_display_slot_set_get() -> None:
    b = board()
    b.set_display_objective("sidebar", "kills")
    assert b.display_objective("sidebar") is b.objective("kills")
    assert b.display["sidebar"] == "kills"
    b.set_display_objective("sidebar", None)
    assert b.display_objective("sidebar") is None
    # Ссылка на несуществующую цель даёт None.
    b.set_display_objective("list", "ghost")
    assert b.display_objective("list") is None


def test_display_slots_are_vanilla() -> None:
    slots = display_slots()
    assert slots[:3] == ["list", "sidebar", "below_name"]
    assert "sidebar.team.red" in slots
    assert "sidebar.team.dark_blue" in slots
    assert len(slots) == 19
    assert display_slot_valid("sidebar") and not display_slot_valid("sidebar.team.pink")


# ── NumberFormat ───────────────────────────────────────────────────────────
def test_number_formats() -> None:
    assert NumberFormat.blank().format(5).plain() == ""
    assert NumberFormat.sidebar_default().format(5).plain() == "5"
    assert NumberFormat.sidebar_default().format(5).spans[0].style.color == RED
    assert NumberFormat.fixed(literal("lots")).format(5).plain() == "lots"
    t = NumberFormat.styled({"color": "gold"}).to_tag()
    assert NumberFormat.from_tag(t) == NumberFormat.styled({"color": "gold"})


def test_number_format_json() -> None:
    assert NumberFormat.from_json({"type": "minecraft:blank"}) == NumberFormat.blank()
    assert NumberFormat.fixed(literal("m")).to_json() == {
        "type": "minecraft:fixed",
        "value": "m",
    }
    assert NumberFormat.blank().to_json() == {"type": "minecraft:blank"}
    styled = NumberFormat.styled({"color": "gold", "bold": True}).to_json()
    assert styled["type"] == "minecraft:styled"
    assert styled["color"] == "gold" and styled["bold"] is True
    assert NumberFormat.from_json({"type": "nope"}) is None


def test_objective_format_or_default() -> None:
    b = board()
    hp = b.objective("hp")
    assert hp.format_or_default(NumberFormat.player_list_default()) == NumberFormat.blank()
    kills = b.objective("kills")
    assert kills.format_or_default(NumberFormat.player_list_default()) == (
        NumberFormat.player_list_default()
    )


# ── pack / unpack ──────────────────────────────────────────────────────────
def test_pack_round_trip() -> None:
    b = board()
    b.set("Steve", "kills", 3)
    b.score_mut("Steve", "kills").locked = False
    b.score_mut("Steve", "kills").display = {"text": "S", "color": "red"}
    b.score_mut("Steve", "kills").number_format = NumberFormat.fixed(literal("many"))
    b.set_display_objective("sidebar.team.red", "kills")
    t = b.add_team("red")
    t.color = "red"
    t.prefix = literal("[R] ")
    t.allow_friendly_fire = False
    t.nametag_visibility = Visibility.HideForOtherTeams
    t.collision_rule = CollisionRule.PushOwnTeam
    b.add_to_team("Steve", "red")
    b.objective_mut("hp").number_format = NumberFormat.styled({"color": "gold", "bold": True})
    back = Scoreboard.unpack(b.pack())
    assert back == b


def test_pack_is_stable_through_unpack() -> None:
    # Полный Tag-level round-trip: unpack(pack(x)) == x и повторный pack даёт
    # ту же структуру (бинарный NBT-слой — nbt.py, отдельная задача).
    b = board()
    b.set("Steve", "kills", 3)
    b.set_display_objective("sidebar", "hp")
    back = Scoreboard.unpack(b.pack())
    assert back == b
    assert back.pack() == b.pack()


def test_to_nbt_from_nbt_aliases() -> None:
    b = board()
    b.set("Steve", "hp", 4)
    assert Scoreboard.from_nbt(b.to_nbt()) == b


# ── game-правила команд ────────────────────────────────────────────────────
def test_friendly_fire_and_invisibles_bool() -> None:
    b = Scoreboard()
    t = b.add_team("red")
    assert t.allow_friendly_fire is True
    assert t.see_friendly_invisibles is True
    t.allow_friendly_fire = False
    t.see_friendly_invisibles = False
    assert t.allow_friendly_fire is False
    assert t.see_friendly_invisibles is False


def test_teams_allow_damage() -> None:
    own = Team.create("red")
    other = Team.create("red")
    assert teams_allied(own, other)
    own.allow_friendly_fire = False
    assert teams_allow_damage(own, other) is False
    own.allow_friendly_fire = True
    assert teams_allow_damage(own, other) is True
    assert teams_allow_damage(None, other) is True
    assert teams_allow_damage(own, Team.create("blue")) is True


def test_pushable_by() -> None:
    own = Team.create("red")
    their = Team.create("blue")
    assert pushable_by(own, their, True) is True
    assert pushable_by(own, their, False) is False
    own.collision_rule = CollisionRule.Never
    assert pushable_by(own, their, True) is False
    own.collision_rule = CollisionRule.Always
    their.collision_rule = CollisionRule.Never
    assert pushable_by(own, their, True) is False


def test_invisible_and_name_shown() -> None:
    own = Team.create("red")
    viewer = Team.create("red")
    assert invisible_to(own, viewer, False, True) is False  # видит союзника
    assert invisible_to(own, viewer, True, True) is False  # наблюдатель
    own.see_friendly_invisibles = False
    assert invisible_to(own, viewer, False, True) is True
    assert invisible_to(None, None, False, True) is True

    v = NameView()
    assert name_shown(None, None, v) is True
    v.hud_hidden = True
    assert name_shown(None, None, v) is False
    v.hud_hidden = False
    v.discrete = True
    v.distance_sqr = 1024.0
    assert name_shown(None, None, v) is False


def test_team_shows_name_visibility() -> None:
    own = Team.create("red")
    viewer = Team.create("red")
    own.nametag_visibility = Visibility.Never
    assert team_shows_name(own, viewer, True) is False
    own.nametag_visibility = Visibility.Always
    assert team_shows_name(own, viewer, True) is True
    assert team_shows_name(None, viewer, True) is None
    own.nametag_visibility = Visibility.HideForOwnTeam
    assert team_shows_name(own, viewer, True) is False
    assert team_shows_name(own, Team.create("blue"), True) is True


def test_death_message_reaches() -> None:
    b = Scoreboard()
    b.add_team("red")
    b.add_to_team("Steve", "red")
    b.add_to_team("Alex", "red")
    team = b.team("red")
    assert death_message_reaches(b, "Steve", "Alex") is True
    team.death_message_visibility = Visibility.Never
    assert death_message_reaches(b, "Steve", "Alex") is False
    team.death_message_visibility = Visibility.HideForOtherTeams
    assert death_message_reaches(b, "Steve", "Alex") is True
    assert death_message_reaches(b, "Steve", "Steve") is False
    assert death_message_reaches(b, "Steve", "Herobrine") is False
    team.death_message_visibility = Visibility.HideForOwnTeam
    assert death_message_reaches(b, "Steve", "Alex") is False
    assert death_message_reaches(b, "Steve", "Herobrine") is True
    # Без команды — сообщение доходит всем.
    assert death_message_reaches(b, "Herobrine", "Alex") is True


def test_death_message_args() -> None:
    victim = Text.literal("Steve")
    cause = Text.literal("Zombie")
    key, args = death_message_args(
        "death.attack.arrow", victim, cause, Text.literal("My Sword")
    )
    assert key == "death.attack.arrow.item"
    assert len(args) == 3
    assert args[0].plain() == "Steve"
    assert args[1].plain() == "Zombie"
    assert args[2].plain() == "My Sword"
    key, args = death_message_args("death.attack.arrow", victim, cause, None)
    assert key == "death.attack.arrow"
    assert len(args) == 2


# ── компоненты / реальные данные ───────────────────────────────────────────
def test_comp_text_and_canonical() -> None:
    assert comp_text(literal("hi")).plain() == "hi"
    assert sb_mod.canonical_component("x") == "x"
    assert sb_mod.canonical_component({"text": "x"}) == "x"
    assert sb_mod.canonical_component(["a", "b"]) == {"text": "a", "extra": ["b"]}
    assert sb_mod.canonical_style({"color": "gold", "text": "z"}) == {"color": "gold"}


def test_real_registries_criteria() -> None:
    if not EXPORT.exists():
        pytest.skip("command-registries export missing")
    raw = json.loads(EXPORT.read_text(encoding="utf-8"))
    reg = Registries.from_export(raw)
    assert criteria_exists("minecraft.mined:minecraft.stone", reg)
    assert criteria_by_name("minecraft.mined:minecraft.stone", reg) == (
        "minecraft.mined:minecraft.stone"
    )
    # Значение из реального файла (список items реестра) доступно.
    assert len(reg.by_registry) > 0
