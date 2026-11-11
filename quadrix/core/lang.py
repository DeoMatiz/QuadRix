# Порт horizon-client-core/src/lang.rs (Minecraft 26.3).
#
# Языки (ClientLanguage / LanguageManager): `lang/<code>.json` из ресурсного
# корня и включённых пакетов поверх `en_us`, список языков из секции
# `language` в `pack.mcmeta`, и текущий язык процесса, которым пользуются
# все экраны.
#
# Точное соответствие Rust:
#   LanguageInfo / Language::load / Language::get / Language::len / is_empty
#   available / apply_deprecated / read_lang_file
#   set / current / scoped / bidirectional / code / get / get_or / has / tr
#
# Дополнительно (нужно GUI и quadrix/core/text.py): `format_translation`
# с Java-семантикой `String.format` (`%s`, `%1$s`, `%d`, `%1$d`, `%%`),
# `Language.tr`/`translate` и алиасы `get_with_fallback`/`get_or_default`.
#
# FALLBACK: `Bundled` (встроенные строки Horizon) читает файлы из
# `crates/horizon-client/assets/horizon/lang/`; если каталога нет, источник
# просто ничего не отдаёт. В Rust файлы вкомпилированы через include_str!.

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

__all__ = [
    "DEFAULT",
    "LanguageInfo",
    "Language",
    "ResourceSource",
    "MemorySource",
    "PathSource",
    "Bundled",
    "apply_deprecated",
    "read_lang_file",
    "available",
    "set",
    "current",
    "scoped",
    "bidirectional",
    "code",
    "get",
    "get_or",
    "get_with_fallback",
    "get_or_default",
    "has",
    "tr",
    "translate",
    "format_translation",
    "load",
    "load_from",
]

DEFAULT = "en_us"


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] lang: " + message)


# ── ResourceSource ────────────────────────────────────────────────────────
@runtime_checkable
class ResourceSource(Protocol):
    """Источник файлов ресурсов: подготовленный корень плюс паки,
    в порядке возрастания приоритета (поздние перекрывают ранние)."""

    def read(self, path: str) -> Optional[bytes]:
        ...

    def exists(self, path: str) -> bool:
        return self.read(path) is not None

    def namespaces(self) -> List[str]:
        return ["minecraft"]


@dataclass
class MemorySource:
    """Источник в памяти (Rust `Mem` из тестов): путь → байты."""

    files: Dict[str, bytes] = field(default_factory=dict)

    def read(self, path: str) -> Optional[bytes]:
        return self.files.get(path)

    def exists(self, path: str) -> bool:
        return path in self.files

    def namespaces(self) -> List[str]:
        return ["minecraft"]


@dataclass
class PathSource:
    """Подготовленный корень ресурсов (`std::path::PathBuf`): `root/path`."""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    def read(self, path: str) -> Optional[bytes]:
        try:
            return (self.root / path).read_bytes()
        except OSError:
            return None

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def namespaces(self) -> List[str]:
        """Имена подкаталогов `assets/` (паки могут добавлять свои)."""
        base = self.root / "assets"
        try:
            return sorted(e.name for e in base.iterdir() if e.is_dir())
        except OSError:
            return []


class Bundled:
    """Собственные строки Horizon, вкомпилированные в Rust. Здесь читаются
    из дерева репозитория (`crates/horizon-client/assets/horizon/lang/`)."""

    # quadrix/core/lang.py → quadrix/core → quadrix → <repo>
    _REPO = Path(__file__).resolve().parents[2]
    _DIR = _REPO / "horizon" / "crates" / "horizon-client" / "assets" / "horizon" / "lang"

    def read(self, path: str) -> Optional[bytes]:
        prefix = "assets/horizon/lang/"
        if not path.startswith(prefix):
            return None
        name = path[len(prefix):]
        if not name.endswith(".json") or "/" in name:
            return None
        try:
            body = (self._DIR / name).read_text(encoding="utf-8")
        except OSError:
            return None
        # Швейцарский немецкий пишет "ss" вместо "ß", как de_ch у vanilla.
        if name == "de_ch.json":
            body = body.replace("ß", "ss")
        return body.encode("utf-8")

    def exists(self, path: str) -> bool:
        return self.read(path) is not None

    def namespaces(self) -> List[str]:
        return ["horizon"]


# ── LanguageInfo / Language ──────────────────────────────────────────────
@dataclass
class LanguageInfo:
    code: str
    name: str
    region: str
    bidirectional: bool = False

    def label(self) -> str:
        """LanguageInfo.toComponent: "Name (Region)"."""
        return "{} ({})".format(self.name, self.region)


@dataclass
class Language:
    code: str = ""
    bidirectional: bool = False
    map: Dict[str, str] = field(default_factory=dict)

    # ── загрузка ──────────────────────────────────────────────────────
    @classmethod
    def load(cls, sources: Sequence[Any], code: str) -> "Language":
        """ClientLanguage.loadFrom: сначала en_us, затем выбранный язык, из
        каждого namespace и каждого источника в порядке приоритета."""
        map_: Dict[str, str] = {}
        codes: List[str] = [DEFAULT]
        if code != DEFAULT:
            codes.append(code)
        # Строки Horizon первыми, чтобы пак или корень могли их перекрыть.
        all_sources: List[Any] = [Bundled()]
        all_sources.extend(sources)
        namespaces = sorted({ns for s in all_sources for ns in s.namespaces()})
        for c in codes:
            for namespace in namespaces:
                for source in all_sources:
                    data = source.read("assets/{}/lang/{}.json".format(namespace, c))
                    if data is None:
                        continue
                    read_lang_file(data, map_)
        # DeprecatedTranslationsInfo.loadFromDefaultResource().applyToMap.
        for source in all_sources:
            data = source.read("assets/minecraft/lang/deprecated.json")
            if data is not None:
                apply_deprecated(map_, data)
                break
        bidirectional = any(
            info.code == code and info.bidirectional for info in available(all_sources)
        )
        return cls(code=code, bidirectional=bidirectional, map=map_)

    @classmethod
    def load_from(cls, path: Any, code: Optional[str] = None) -> "Language":
        """Удобная обёртка: путь к корню ресурсов или к конкретному
        `<code>.json`. Для файла корень выводится из структуры
        `assets/<ns>/lang/<code>.json`; `code` берётся из имени файла."""
        p = Path(path)
        if p.is_dir():
            source: Any = PathSource(p)
            chosen = code if code is not None else DEFAULT
        else:
            source = PathSource(_root_for_lang_file(p))
            chosen = code if code is not None else p.stem
        return cls.load([source], chosen)

    # ── доступ ────────────────────────────────────────────────────────
    def get(self, key: str) -> Optional[str]:
        return self.map.get(key)

    def get_or(self, key: str, fallback: str) -> str:
        v = self.map.get(key)
        return v if v is not None else fallback

    def get_with_fallback(self, key: str, fallback: str) -> str:
        """Алиас `get_or`."""
        return self.get_or(key, fallback)

    def get_or_default(self, key: str) -> str:
        """`ClientLanguage.getOrDefault`: перевод, иначе сам ключ."""
        v = self.map.get(key)
        return v if v is not None else key

    def tr(self, key: str, args: Optional[Sequence[Any]] = None) -> str:
        """Перевод ключа с подстановкой аргументов (Java String.format)."""
        return format_translation(self.get_or_default(key), args or [])

    translate = tr

    def len(self) -> int:
        return len(self.map)

    def is_empty(self) -> bool:
        return not self.map

    def __len__(self) -> int:
        return len(self.map)

    def __contains__(self, key: object) -> bool:
        return key in self.map


def _root_for_lang_file(path: Path) -> Path:
    """`<root>/assets/<ns>/lang/<code>.json` → `<root>`."""
    parts = path.resolve().parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in ("lang",):
            # <root>/assets/<ns>/lang/<file> → отступаем ns и assets.
            return Path(*parts[: i - 2]) if i >= 3 else path.parent
    return path.parent


# ── deprecated translations ──────────────────────────────────────────────
def apply_deprecated(map_: Dict[str, str], data: Any) -> None:
    """DeprecatedTranslationsInfo.applyToMap: убрать удалённые ключи, затем
    перенести текст переименованного ключа на новый (отсутствие старого
    удаляет новый)."""
    try:
        info = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
    except (ValueError, AttributeError):
        return
    if not isinstance(info, dict):
        return
    for key in info.get("removed", []) or []:
        if isinstance(key, str):
            map_.pop(key, None)
    renamed = info.get("renamed", {})
    if isinstance(renamed, dict):
        for frm, to in renamed.items():
            if not isinstance(to, str):
                continue
            if frm in map_:
                map_[to] = map_.pop(frm)
            else:
                map_.pop(to, None)


# ── чтение одного lang-файла ─────────────────────────────────────────────
def read_lang_file(data: Any, map_: Dict[str, str]) -> None:
    """`Language.loadFromJson` для одного `lang/<code>.json`: записи идут в
    `map_` в порядке файла. Плоский JSON читается обычным парсером; иначе —
    снисходительный ридер Gson (комментарии `#`, `//`, `/* */`, имена и
    значения без кавычек или в одинарных кавычках, `=`/`=>` и `;`).
    Значение не-строка/число/булево (null, массив, объект) завершает файл.
    """
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else data
    # Плоский JSON: как serde_json в HashMap<String, String> — только строки.
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if isinstance(obj, dict) and all(isinstance(v, str) for v in obj.values()):
        map_.update(obj)
        return
    # Gson's JsonReader пропускает ведущий BOM.
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        parsed = _LenientParser(text).parse()
    except ValueError:
        return
    if parsed is None or parsed[0] != "obj":
        return
    for key, value in parsed[1]:
        v = _json_value_to_text(value)
        if v is None:
            break
        map_[key] = v


def _json_value_to_text(value: Tuple[str, Any]) -> Optional[str]:
    kind, payload = value
    if kind == "str":
        return payload
    if kind == "num":
        return payload
    if kind == "bool":
        return "true" if payload else "false"
    return None  # null / массив / объект — завершают файл


# Снисходительный JSON-ридер в духе Gson JsonReader (horizon_world::datafix::json).
class _LenientParser:
    _WS = " \t\r\n\f"
    _NAME_STOP = " \t\r\n:,;=}{[]/"
    _VALUE_STOP = " \t\r\n:,;}{[]/*#"

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)

    def parse(self) -> Optional[Tuple[str, Any]]:
        self._skip()
        value = self._value()
        self._skip()
        if self.i != self.n:
            raise ValueError("хвост после значения")
        return value

    def _skip(self) -> None:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in self._WS:
                self.i += 1
            elif c == "#":
                self._to_eol()
            elif c == "/" and self.i + 1 < self.n and s[self.i + 1] == "/":
                self._to_eol()
            elif c == "/" and self.i + 1 < self.n and s[self.i + 1] == "*":
                self.i += 2
                while self.i < self.n and not (s[self.i] == "*" and self.i + 1 < self.n and s[self.i + 1] == "/"):
                    self.i += 1
                self.i += 2
            else:
                break

    def _to_eol(self) -> None:
        while self.i < self.n and self.s[self.i] != "\n":
            self.i += 1

    def _value(self) -> Tuple[str, Any]:
        self._skip()
        if self.i >= self.n:
            raise ValueError("конец ввода")
        c = self.s[self.i]
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c in "\"'":
            return ("str", self._string())
        if c.isdigit() or c in "-+.":
            return ("num", self._number())
        if c.isalpha():
            word = self._until(self._VALUE_STOP)
            if word == "true":
                return ("bool", True)
            if word == "false":
                return ("bool", False)
            if word == "null":
                return ("null", None)
            return ("str", word)
        return ("str", self._until(self._VALUE_STOP))

    def _object(self) -> Tuple[str, List[Tuple[str, Any]]]:
        self.i += 1  # '{'
        entries: List[Tuple[str, Any]] = []
        self._skip()
        if self.i < self.n and self.s[self.i] == "}":
            self.i += 1
            return ("obj", entries)
        while True:
            self._skip()
            name = self._name()
            self._skip()
            if self.i < self.n and self.s[self.i] == ":":
                self.i += 1
            elif self.i < self.n and self.s[self.i] == "=":
                self.i += 1
                if self.i < self.n and self.s[self.i] == ">":
                    self.i += 1
            else:
                raise ValueError("нет разделителя имени")
            value = self._value()
            entries.append((name, value))
            self._skip()
            if self.i >= self.n:
                raise ValueError("объект не закрыт")
            c = self.s[self.i]
            if c in ",;":
                self.i += 1
                continue
            if c == "}":
                self.i += 1
                return ("obj", entries)
            raise ValueError("неожиданный символ " + repr(c))

    def _array(self) -> Tuple[str, List[Any]]:
        self.i += 1  # '['
        values: List[Any] = []
        self._skip()
        if self.i < self.n and self.s[self.i] == "]":
            self.i += 1
            return ("arr", values)
        while True:
            values.append(self._value())
            self._skip()
            if self.i >= self.n:
                raise ValueError("массив не закрыт")
            c = self.s[self.i]
            if c in ",;":
                self.i += 1
                continue
            if c == "]":
                self.i += 1
                return ("arr", values)
            raise ValueError("неожиданный символ " + repr(c))

    def _name(self) -> str:
        self._skip()
        if self.i < self.n and self.s[self.i] in "\"'":
            return self._string()
        name = self._until(self._NAME_STOP)
        if name == "":
            raise ValueError("пустое имя")
        return name

    def _string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        buf: List[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self.i += 1
                if self.i >= self.n:
                    raise ValueError("обрыв escape")
                e = self.s[self.i]
                buf.append({
                    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
                    '"': '"', "'": "'", "\\": "\\", "/": "/",
                }.get(e, e))
                self.i += 1
                continue
            if c == quote:
                self.i += 1
                return "".join(buf)
            buf.append(c)
            self.i += 1
        raise ValueError("строка не закрыта")

    def _number(self) -> str:
        start = self.i
        while self.i < self.n and self.s[self.i] in "0123456789+-.eE":
            self.i += 1
        return self.s[start:self.i]

    def _until(self, stop: str) -> str:
        start = self.i
        while self.i < self.n and self.s[self.i] not in stop:
            self.i += 1
        return self.s[start:self.i]


# ── список доступных языков ──────────────────────────────────────────────
def available(sources: Sequence[Any]) -> List[LanguageInfo]:
    """Языки, объявленные в `pack.mcmeta` (корень vanilla идёт первым)."""
    found: Dict[str, LanguageInfo] = {
        DEFAULT: LanguageInfo(code=DEFAULT, name="English", region="US", bidirectional=False)
    }
    for source in sources:
        for path in ("assets/pack.mcmeta", "pack.mcmeta"):
            data = source.read(path)
            if data is None:
                continue
            try:
                value = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
            except (ValueError, AttributeError):
                continue
            if not isinstance(value, dict):
                continue
            langs = value.get("language")
            if not isinstance(langs, dict):
                continue
            for code, info in langs.items():
                info = info if isinstance(info, dict) else {}
                # Выбираемы только языки, чей файл где-то есть.
                file = "assets/minecraft/lang/{}.json".format(code)
                if code != DEFAULT and not any(s.exists(file) for s in sources):
                    continue
                found[code] = LanguageInfo(
                    code=code,
                    name=info.get("name", code) if isinstance(info.get("name"), str) else code,
                    region=info.get("region", "") if isinstance(info.get("region"), str) else "",
                    bidirectional=bool(info.get("bidirectional", False)),
                )
    return [found[k] for k in sorted(found)]


# ── текущий язык процесса ────────────────────────────────────────────────
_GLOBAL_CURRENT: Optional[Language] = None
_GLOBAL_BIDIRECTIONAL = False
_LOCAL = threading.local()


def _scope() -> Optional[Dict[str, Any]]:
    return getattr(_LOCAL, "scope", None)


def _missed(key: str) -> None:
    """`key` спросили у scoped-языка, а текста для него нет."""
    sc = _scope()
    if sc is not None and key not in sc["missed"]:
        sc["missed"].append(key)


def set(language: Language) -> None:
    """Сделать `language` текущим языком процесса."""
    global _GLOBAL_CURRENT, _GLOBAL_BIDIRECTIONAL
    _GLOBAL_BIDIRECTIONAL = bool(language.bidirectional)
    _GLOBAL_CURRENT = language
    # Мост в quadrix/core/text.py: заменяем FALLBACK на настоящий язык.
    try:
        from quadrix.core import text as _text
    except Exception:  # pragma: no cover - text не обязателен
        _text = None
    if _text is not None:
        _text._CURRENT_LANG = language


def current() -> Optional[Language]:
    sc = _scope()
    if sc is not None:
        return sc["language"]
    return _GLOBAL_CURRENT


def scoped(language: Language, fn: Callable[[], Any]) -> Tuple[Any, List[str]]:
    """Запустить `fn` с `language` текущим только в этом потоке и вернуть
    (результат, ключи, которых у языка не было, в порядке спроса, без
    повторов). Области вкладываются: внутренняя выигрывает."""
    outer = getattr(_LOCAL, "scope", None)
    _LOCAL.scope = {"language": language, "missed": []}
    result = fn()
    missed = _LOCAL.scope["missed"]
    _LOCAL.scope = outer
    return result, missed


def bidirectional() -> bool:
    """`ClientLanguage.defaultRightToLeft` текущего языка процесса."""
    return _GLOBAL_BIDIRECTIONAL


def code() -> str:
    lang = current()
    return lang.code if lang is not None else DEFAULT


def get(key: str) -> str:
    """Language.getOrDefault: перевод, иначе сам ключ."""
    lang = current()
    if lang is not None:
        v = lang.get(key)
        if v is not None:
            return v
    _missed(key)
    return key


def get_or(key: str, fallback: str) -> str:
    """Перевод, иначе `fallback`."""
    lang = current()
    if lang is not None:
        v = lang.get(key)
        if v is not None:
            return v
    _missed(key)
    return fallback


def get_with_fallback(key: str, fallback: str) -> str:
    """Алиас `get_or`."""
    return get_or(key, fallback)


def get_or_default(key: str) -> str:
    """Алиас `get`."""
    return get(key)


def has(key: str) -> bool:
    lang = current()
    return lang is not None and lang.get(key) is not None


def tr(key: str, args: Optional[Sequence[Any]] = None) -> str:
    """I18n.get с простыми строковыми аргументами."""
    from quadrix.core.text import Text

    return Text.tr(key, args or []).plain()


def translate(key: str, args: Optional[Sequence[Any]] = None) -> str:
    """`get` + `format_translation`: перевод ключа с подстановкой аргументов."""
    return format_translation(get(key), args or [])


def load(root: Any, code: str = DEFAULT) -> Language:
    """Загрузить язык `code` из корня ресурсов `root`."""
    return Language.load([PathSource(root)], code)


def load_from(path: Any, code: Optional[str] = None) -> Language:
    """Загрузить язык из корня ресурсов или конкретного `<code>.json`."""
    return Language.load_from(path, code)


# ── форматирование как Java String.format ────────────────────────────────
_FORMAT_RE = re.compile(r"%(?:(\d+)\$)?([A-Za-z%])")


def format_translation(template: str, args: Sequence[Any]) -> str:
    """Java `String.format`: `%s`/`%d` — следующий аргумент, `%1$s`/`%1$d` —
    нумерованный (индекс с 1!), `%%` — знак процента. Это НЕ Python `.format`:
    порядок аргументов задаёт шаблон."""
    out: List[str] = []
    next_index = 0
    i = 0
    n = len(template)
    while i < n:
        if template[i] != "%":
            out.append(template[i])
            i += 1
            continue
        m = _FORMAT_RE.match(template, i)
        if m is None:
            out.append("%")
            i += 1
            continue
        number, conv = m.group(1), m.group(2)
        if number is None and conv == "%":
            out.append("%")
            i = m.end()
            continue
        if number is not None:
            index = int(number) - 1
        else:
            index = next_index
            next_index += 1
        if index < 0 or index >= len(args):
            # Java бросил бы исключение; показываем спецификатор дословно.
            out.append(m.group(0))
            i = m.end()
            continue
        arg = args[index]
        out.append(_format_arg(conv, arg))
        i = m.end()
    return "".join(out)


def _format_arg(conversion: str, arg: Any) -> str:
    if conversion == "d" or conversion == "x" or conversion == "o":
        try:
            value = int(arg)
        except (TypeError, ValueError):
            return str(arg)
        return format(value, {"d": "d", "x": "x", "o": "o"}[conversion])
    if conversion == "f":
        try:
            return str(float(arg))
        except (TypeError, ValueError):
            return str(arg)
    if conversion == "b":
        return "true" if _java_truthy(arg) else "false"
    return str(arg)


def _java_truthy(arg: Any) -> bool:
    if arg is None:
        return False
    if isinstance(arg, bool):
        return arg
    if isinstance(arg, str):
        return arg.lower() == "true"
    return True
