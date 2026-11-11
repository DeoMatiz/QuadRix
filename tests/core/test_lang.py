# Тесты порта horizon-client-core/src/lang.rs → quadrix/core/lang.py.
#
# Загружаем реальный `en_us.json` из `.local/horizon-client/26.3` и
# проверяем доступ, Jава-форматирование (`%s`/`%1$s`/`%d`/`%1$d`),
# снисходительный ридер Gson и scoped-язык.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quadrix.core import lang as langmod
from quadrix.core.lang import (
    Bundled,
    Language,
    LanguageInfo,
    MemorySource,
    PathSource,
    available,
    apply_deprecated,
    format_translation,
    read_lang_file,
)

REPO = Path(__file__).resolve().parents[2]
LANG_DIR = REPO / ".local" / "horizon-client" / "26.3" / "assets" / "minecraft" / "lang"
EN_US = LANG_DIR / "en_us.json"
RU_RU = LANG_DIR / "ru_ru.json"


@pytest.fixture(scope="module")
def en() -> Language:
    assert EN_US.is_file(), "нет реального en_us.json в .local"
    return Language.load([PathSource(REPO / ".local" / "horizon-client" / "26.3")], "en_us")


# ── загрузка и доступ ────────────────────────────────────────────────────
def test_load_en_us_not_empty(en: Language) -> None:
    raw = json.loads(EN_US.read_text(encoding="utf-8"))
    assert en.len() >= len(raw)
    assert not en.is_empty()


def test_get_known_key(en: Language) -> None:
    assert en.get("block.minecraft.stone") == "Stone"
    assert en.get("item.minecraft.apple") == "Apple"


def test_get_unknown_key_is_none(en: Language) -> None:
    assert en.get("does.not.exist") is None


def test_module_get_falls_back_to_key(en: Language) -> None:
    def body() -> None:
        assert langmod.get("nonexistent.key") == "nonexistent.key"

    langmod.scoped(en, body)


def test_module_get_or_returns_default(en: Language) -> None:
    def body() -> None:
        assert langmod.get_or("nonexistent", "default") == "default"
        assert langmod.get_with_fallback("nonexistent", "default") == "default"

    langmod.scoped(en, body)


def test_language_get_or_and_get_or_default(en: Language) -> None:
    assert en.get_or("nope", "fallback") == "fallback"
    assert en.get_or_default("block.minecraft.stone") == "Stone"
    assert en.get_or_default("nope") == "nope"


def test_cache_same_key_returns_identical_value(en: Language) -> None:
    first = en.get("block.minecraft.stone")
    second = en.get("block.minecraft.stone")
    assert first is second  # тот же объект из dict, без пересчёта


# ── Java String.format ───────────────────────────────────────────────────
def test_format_positional_s() -> None:
    assert format_translation("%s apples", ["5"]) == "5 apples"


def test_format_numbered_s() -> None:
    assert format_translation("%1$s and %2$s", ["a", "b"]) == "a and b"


def test_format_numbered_reordered() -> None:
    # Порядок задаёт шаблон, а не список: %2$s идёт первым.
    assert format_translation("%2$s and %1$s", ["a", "b"]) == "b and a"


def test_format_d_and_percent() -> None:
    assert format_translation("%d items", [42]) == "42 items"
    assert format_translation("%1$d%%", [100]) == "100%"


def test_format_in_language_key() -> None:
    mem = MemorySource({
        "assets/minecraft/lang/en_us.json": b'{"key.with.%s": "value %s"}',
    })
    lang = Language.load([mem], "en_us")
    assert lang.get("key.with.%s") == "value %s"
    assert lang.tr("key.with.%s", ["X"]) == "value X"

    def body() -> None:
        assert langmod.translate("key.with.%s", ["Y"]) == "value Y"

    langmod.scoped(lang, body)


# ── второй язык ──────────────────────────────────────────────────────────
def test_load_ru_ru() -> None:
    if not RU_RU.is_file():
        pytest.skip("нет ru_ru.json в .local")
    ru = Language.load_from(RU_RU)
    assert ru.code == "ru_ru"
    assert ru.get("block.minecraft.stone") != "Stone"
    assert ru.get("block.minecraft.stone")  # непустая строка


def test_load_from_directory_uses_code() -> None:
    lang = Language.load_from(REPO / ".local" / "horizon-client" / "26.3", "en_us")
    assert lang.code == "en_us"
    assert lang.get("block.minecraft.stone") == "Stone"


# ── scoped текущий язык ──────────────────────────────────────────────────
def test_scoped_reports_missing_keys() -> None:
    mem = MemorySource({
        "assets/minecraft/lang/en_us.json": b'{"known": "Known"}',
    })
    language = Language.load([mem], "en_us")
    hits: dict = {}

    def body() -> None:
        hits["known"] = langmod.get("known")
        hits["missing"] = langmod.get("missing.key")
        hits["fallback"] = langmod.get_or("no.fallback", "English")

    result, missed = langmod.scoped(language, body)
    assert hits["known"] == "Known"
    assert hits["missing"] == "missing.key"
    assert hits["fallback"] == "English"
    assert missed == ["missing.key", "no.fallback"]
    # Область кончилась вместе с замыканием.
    assert langmod.code() == langmod.DEFAULT


# ── снисходительный ридер Gson ───────────────────────────────────────────
def _read(body: str) -> dict:
    m: dict = {}
    read_lang_file(body.encode("utf-8"), m)
    return m


def test_read_plain_json_like_serde() -> None:
    body = '{"a": "Apple \\"quoted\\" \\u00e9", "b": "", "a": "Again"}'
    assert _read(body) == {"a": "Again", "b": ""}


def test_read_comments() -> None:
    want = {"a": "Apple", "b": "Banana # not a comment // either"}
    for body in [
        '# header\n{\n# a comment\n"a": "Apple",\n"b": "Banana # not a comment // either"\n}\n',
        '// header\n{"a": "Apple", // after\n"b": "Banana # not a comment // either"}',
        '/* header\n over lines */{"a": /* inline */ "Apple", "b": "Banana # not a comment // either"}',
    ]:
        assert _read(body) == want, body


def test_read_unquoted_and_single_quoted() -> None:
    assert _read("{a: 'Apple', 'b': \"Banana\", c: Cherry}") == {
        "a": "Apple", "b": "Banana", "c": "Cherry",
    }
    assert _read("{'a': 'say \"hi\"', \"b\": \"it's\"}") == {"a": 'say "hi"', "b": "it's"}


def test_read_gson_separators_and_bom() -> None:
    assert _read('\ufeff{"a" = "Apple"; "b" => "Banana"}') == {"a": "Apple", "b": "Banana"}
    # Запятая перед `}` — не JSON даже для снисходительного ридера.
    assert _read('{# c\n"a": "Apple",}') == {}


def test_numbers_and_booleans_read_as_text() -> None:
    assert _read('{"a": 1.50, "b": true, "c": -2e3}') == {
        "a": "1.50", "b": "true", "c": "-2e3",
    }


def test_a_non_text_value_ends_the_file() -> None:
    assert _read('# c\n{"a": "Apple", "b": ["x"], "c": "Cherry"}') == {"a": "Apple"}
    assert _read('{"a": null, "b": "Banana"}') == {}


def test_not_json_adds_nothing() -> None:
    for body in ['# c\n{"a": "Apple"', '["a"]', '"a"', "", '{"a": "Apple"} {']:
        assert _read(body) == {}, body


# ── deprecated / available ───────────────────────────────────────────────
def test_apply_deprecated_removes_and_renames() -> None:
    m = {"old": "Text", "gone": "X", "new": "Stale"}
    data = json.dumps({"removed": ["gone"], "renamed": {"old": "new"}})
    apply_deprecated(m, data)
    assert "gone" not in m
    assert m["new"] == "Text"


def test_available_lists_only_existing_languages() -> None:
    base = MemorySource({
        "assets/minecraft/lang/en_us.json": b"{}",
        "assets/minecraft/lang/fr_fr.json": b"{}",
        "assets/pack.mcmeta": json.dumps({"language": {
            "fr_fr": {"name": "Français", "region": "France"},
            "de_de": {"name": "Deutsch", "region": "Deutschland"},
        }}).encode("utf-8"),
    })
    langs = available([base])
    assert [l.code for l in langs] == ["en_us", "fr_fr"]
    assert langs[1].label() == "Français (France)"


def test_bundled_serves_horizon_strings() -> None:
    en = Language.load([], "en_us")
    # Строка из собственных assets/horizon клиента.
    if en.get("horizon.options.controller") is None:
        pytest.skip("нет horizon bundled lang в дереве репозитория")
    assert en.get("horizon.options.controller") == "Controller"


def test_language_info_label() -> None:
    assert LanguageInfo("en_us", "English", "US").label() == "English (US)"
