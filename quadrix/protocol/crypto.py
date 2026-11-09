# Порт horizon-protocol/src/crypto.rs (+ rsa.rs, нужная для login часть).
#
# Здесь живёт криптография сетевого протокола vanilla 26.3:
#   * AES/CFB8 — потоковый шифр соединения (Crypt.getCipher): ключ
#     и IV — один и тот же 16-байтовый shared secret;
#   * случайный shared secret (Crypt.generateSecretKey);
#   * server hash для online-mode (Crypt.digestData) и java_hex_digest;
#   * MD5 и offline UUID (UUIDUtil.createOfflinePlayerUUID);
#   * RSA из rsa.rs: публичный ключ сервера (Crypt.byteToPublicKey),
#     PKCS#1 v1.5 шифрование/дешифрование (Crypt.encryptUsingKey /
#     Crypt.decryptUsingKey), генерация пары сервером и DER.
#
# Сознательно НЕ портируется:
#   * secure_chat.rs — отдельный протокол подписей чата (потом);
#   * самописная арифметика Montgomery/Big из rsa.rs — вместо неё
#     `cryptography`, как требует задание (никакого самописного RSA).
#
# Имена и поля сохранены как в Rust: Cfb8, RsaPublicKey, RsaPrivateKey,
# SignatureHash, generate_secret, server_hash, java_hex_digest, md5,
# offline_uuid, uuid_string. Для удобства connection.rs добавлены
# CFB8Encryptor / CFB8Decryptor / MinecraftCipher (Cipher).

from __future__ import annotations

import hashlib
import os
from enum import Enum
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher
from cryptography.hazmat.primitives.ciphers import algorithms

# CFB8 с недавних пор переехал в decrepit; держим оба пути, чтобы
# работать и на старых, и на новых версиях `cryptography`.
try:  # pragma: no cover - зависит от версии библиотеки
    from cryptography.hazmat.decrepit.ciphers.modes import CFB8 as _CFB8
except ImportError:  # pragma: no cover
    from cryptography.hazmat.primitives.ciphers.modes import CFB8 as _CFB8

from quadrix.protocol.buf import ProtocolError

__all__ = [
    # AES/CFB8
    "Cfb8",
    "CFB8Encryptor",
    "CFB8Decryptor",
    "MinecraftCipher",
    "Cipher",
    # случайность
    "random_bytes",
    "generate_secret",
    # хэши / UUID
    "java_hex_digest",
    "server_hash",
    "md5",
    "offline_uuid",
    "uuid_string",
    # RSA
    "SignatureHash",
    "RsaPublicKey",
    "RsaPrivateKey",
    "RsaKeyPair",
]

# rsa.rs:368 — публичная экспонента Java-генератора.
E: int = 65537


def _as_bytes(data) -> bytes:
    """bytes/bytearray/memoryview → неизменяемые bytes."""
    return bytes(data)


# ── AES/CFB8 (crypto.rs:12, crypto/blocks.rs) ────────────────────────

class Cfb8:
    """AES/CFB8 stream state для одного направления соединения.

    В Rust один экземпляр хранит регистр (последние 16 байт шифртекста),
    а `encrypt`/`decrypt` меняют его на месте. В Python `cryptography`
    держит регистр внутри контекста, поэтому у нас два независимых
    контекста на объект: это ровно то, что делает connection.rs, где
    для чтения и записи создаются отдельные `Cfb8` с одним секретом.
    Состояние переживает вызовы (`update`), т.е. потоковый шифр ведёт
    себя как в Rust.
    """

    __slots__ = ("key", "iv", "_enc", "_dec")

    def __init__(self, key, iv):
        key_b = _as_bytes(key)
        iv_b = _as_bytes(iv)
        # crypto.rs:20 — Minecraft берёт 16-байтовый секрет как key и IV.
        if len(key_b) != 16:
            raise ProtocolError(f"AES key must be 16 bytes, got {len(key_b)}")
        if len(iv_b) != 16:
            raise ProtocolError(f"CFB8 IV must be 16 bytes, got {len(iv_b)}")
        self.key = key_b
        self.iv = iv_b
        self._enc = None
        self._dec = None

    def _encryptor(self):
        if self._enc is None:
            self._enc = _Cipher(algorithms.AES(self.key), _CFB8(self.iv)).encryptor()
        return self._enc

    def _decryptor(self):
        if self._dec is None:
            self._dec = _Cipher(algorithms.AES(self.key), _CFB8(self.iv)).decryptor()
        return self._dec

    def encrypt(self, data) -> bytes:
        """Зашифровать очередной кусок потока (crypto.rs:29)."""
        raw = _as_bytes(data)
        if not raw:
            return b""
        return self._encryptor().update(raw)

    def decrypt(self, data) -> bytes:
        """Расшифровать очередной кусок потока (crypto.rs:34)."""
        raw = _as_bytes(data)
        if not raw:
            return b""
        return self._decryptor().update(raw)


class CFB8Encryptor:
    """Шифрующее направление AES/CFB8 с обновляемым состоянием.

    Тонкая обёртка над `Cfb8`; `update` — как у потокового шифра.
    """

    __slots__ = ("_cfb8",)

    def __init__(self, key, iv):
        self._cfb8 = Cfb8(key, iv)

    def update(self, data) -> bytes:
        return self._cfb8.encrypt(data)

    # Синоним в духе Rust `Cfb8::encrypt`.
    def encrypt(self, data) -> bytes:
        return self._cfb8.encrypt(data)


class CFB8Decryptor:
    """Дешифрующее направление AES/CFB8 с обновляемым состоянием."""

    __slots__ = ("_cfb8",)

    def __init__(self, key, iv):
        self._cfb8 = Cfb8(key, iv)

    def update(self, data) -> bytes:
        return self._cfb8.decrypt(data)

    # Синоним в духе Rust `Cfb8::decrypt`.
    def decrypt(self, data) -> bytes:
        return self._cfb8.decrypt(data)


class MinecraftCipher:
    """Готовая пара шифрования/дешифрования на одном shared secret.

    connection.rs:411 (Connection.setEncryptionKey) создаёт два `Cfb8`:
    один на чтение, другой на запись. Этот класс просто держит обе
    стороны вместе, чтобы вызывающий код не путал направления.
    """

    __slots__ = ("secret", "encryptor", "decryptor")

    def __init__(self, secret):
        secret_b = _as_bytes(secret)
        if len(secret_b) != 16:
            raise ProtocolError(
                f"shared secret must be 16 bytes, got {len(secret_b)}"
            )
        self.secret = secret_b
        self.encryptor = CFB8Encryptor(secret_b, secret_b)
        self.decryptor = CFB8Decryptor(secret_b, secret_b)

    def encrypt(self, data) -> bytes:
        return self.encryptor.update(data)

    def decrypt(self, data) -> bytes:
        return self.decryptor.update(data)


# Имя из задания: Cipher.
Cipher = MinecraftCipher


# ── Случайность (crypto.rs:53) ───────────────────────────────────────

def random_bytes(n: int) -> bytes:
    """n байт из криптостойкого ГПСЧ ОС (crypto.rs:54, getrandom::fill)."""
    if n < 0:
        raise ProtocolError("negative random length")
    return os.urandom(n)


def generate_secret() -> bytes:
    """Crypt.generateSecretKey: случайный AES-128 ключ соединения."""
    return random_bytes(16)


# ── Java-хэши (crypto.rs:65) ─────────────────────────────────────────

def java_hex_digest(digest) -> str:
    """`new BigInteger(digest).toString(16)` (crypto.rs:67).

    Дайджест читается как знаковое число в дополнительном коде, в
    нижнем регистре без ведущих нулей; отрицательное — с минусом.
    """
    raw = _as_bytes(digest)
    if not raw:
        raise ProtocolError("empty digest")
    value = int.from_bytes(raw, "big", signed=True)
    if value == 0:
        return "0"
    if value < 0:
        return "-" + format(-value, "x")
    return format(value, "x")


def server_hash(server_id: str, secret, public_key) -> str:
    """Online-mode server hash (crypto.rs:95, Crypt.digestData).

    SHA-1 по server id (ISO-8859-1), shared secret и закодированному
    публичному ключу сервера, затем как знаковое hex-число.
    """
    # ISO-8859-1: символы выше U+00FF становятся '?' (crypto.rs:97).
    latin1 = bytes(ord(ch) if ord(ch) <= 0xFF else 0x3F for ch in server_id)
    sha = hashlib.sha1()
    sha.update(latin1)
    sha.update(_as_bytes(secret))
    sha.update(_as_bytes(public_key))
    return java_hex_digest(sha.digest())


def md5(data) -> bytes:
    """MD5 (RFC 1321) (crypto.rs:109)."""
    return hashlib.md5(_as_bytes(data)).digest()


def offline_uuid(name: str) -> int:
    """UUID.nameUUIDFromBytes("OfflinePlayer:" + name) (crypto.rs:162).

    MD5, версия 3, IETF-вариант; результат — u128 big-endian.
    """
    h = bytearray(md5(("OfflinePlayer:" + name).encode("utf-8")))
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return int.from_bytes(h, "big")


def uuid_string(u: int) -> str:
    """Каноническая форма UUID 8-4-4-4-12 (crypto.rs:169)."""
    h = format(int(u) & ((1 << 128) - 1), "032x")
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


# ── RSA (rsa.rs) ─────────────────────────────────────────────────────

def _strip(int_bytes: bytes) -> bytes:
    """Убрать ведущие нули (rsa.rs:219, strip)."""
    start = 0
    for b in int_bytes:
        if b != 0:
            break
        start += 1
    return int_bytes[start:]


def _magnitude(value: int) -> bytes:
    """Неотрицательное число → big-endian без ведущих нулей."""
    if value < 0:
        raise ProtocolError("negative RSA integer")
    if value == 0:
        return b""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


class SignatureHash(Enum):
    """Дайджест подписи PKCS#1 v1.5 (rsa.rs:298)."""

    Sha1 = "sha1"
    Sha256 = "sha256"
    # Удобные псевдонимы (то же значение → алиасы Enum).
    SHA1 = "sha1"
    SHA256 = "sha256"

    @property
    def algorithm(self):
        """Объект `cryptography`, соответствующий дайджесту."""
        return hashes.SHA1() if self.value == "sha1" else hashes.SHA256()

    def digest(self, message) -> bytes:
        """Сырой дайджест сообщения (rsa.rs:318)."""
        if self.value == "sha1":
            return hashlib.sha1(_as_bytes(message)).digest()
        return hashlib.sha256(_as_bytes(message)).digest()


class RsaPublicKey:
    """X.509 публичный ключ сервера (rsa.rs:213)."""

    __slots__ = ("modulus", "exponent", "_key")

    def __init__(self, key, modulus: bytes, exponent: bytes):
        self._key = key
        self.modulus = modulus
        self.exponent = exponent

    @classmethod
    def from_der(cls, spki) -> "RsaPublicKey":
        """X509EncodedKeySpec: SubjectPublicKeyInfo (rsa.rs:226)."""
        raw = _as_bytes(spki)
        try:
            key = serialization.load_der_public_key(raw)
        except Exception as exc:  # noqa: BLE001 - любая ошибка DER
            raise ProtocolError("Malformed public key") from exc
        if not isinstance(key, rsa.RSAPublicKey):
            raise ProtocolError("Not an RSA public key")
        numbers = key.public_numbers()
        modulus = _strip(_magnitude(numbers.n))
        exponent = _strip(_magnitude(numbers.e))
        # rsa.rs:254 — модуль не короче 64 байт и обязан быть нечётным.
        if len(modulus) < 64 or modulus[-1] & 1 == 0:
            raise ProtocolError("Malformed public key")
        return cls(key, modulus, exponent)

    def size(self) -> int:
        """Длина модуля в байтах (и каждого шифртекста) (rsa.rs:260)."""
        return len(self.modulus)

    def encrypt(self, message) -> bytes:
        """RSAES-PKCS1-v1_5 с случайным непустым паддингом (rsa.rs:275)."""
        msg = _as_bytes(message)
        if len(msg) + 11 > self.size():
            raise ProtocolError("Message too long for the RSA key")
        try:
            return self._key.encrypt(msg, padding.PKCS1v15())
        except Exception as exc:  # noqa: BLE001
            raise ProtocolError("RSA encryption failed") from exc

    def verify(self, hash: SignatureHash, message, signature) -> bool:
        """RSASSA-PKCS1-v1_5 проверка (rsa.rs:332).

        Любая ошибка подписи — это `False`, как отчёт Java-исключений
        в SignatureValidator.
        """
        sig = _as_bytes(signature)
        if len(sig) != self.size():
            return False
        if sig >= self.modulus:
            return False
        try:
            self._key.verify(
                sig,
                _as_bytes(message),
                padding.PKCS1v15(),
                hash.algorithm,
            )
            return True
        except Exception:  # noqa: BLE001 - InvalidSignature и прочее
            return False


class RsaPrivateKey:
    """Пара ключей сервера (rsa.rs:464): публичная часть + приватный ключ."""

    __slots__ = ("public", "_key")

    def __init__(self, key, public: RsaPublicKey):
        self._key = key
        self.public = public

    @classmethod
    def _from_key(cls, key) -> "RsaPrivateKey":
        numbers = key.private_numbers()
        pub_numbers = numbers.public_numbers
        modulus = _strip(_magnitude(pub_numbers.n))
        exponent = _strip(_magnitude(pub_numbers.e))
        if len(modulus) < 64 or modulus[-1] & 1 == 0:
            raise ProtocolError("Malformed private key")
        public = RsaPublicKey(key.public_key(), modulus, exponent)
        return cls(key, public)

    @classmethod
    def generate(cls, bits: int = 1024) -> "RsaPrivateKey":
        """Новая пара с публичной экспонентой 65537 (rsa.rs:481)."""
        bits = int(bits)
        if bits % 8 != 0 or bits < 512:
            raise ProtocolError(f"invalid RSA key size: {bits}")
        try:
            key = rsa.generate_private_key(public_exponent=E, key_size=bits)
        except Exception as exc:  # noqa: BLE001
            raise ProtocolError("RSA key generation failed") from exc
        return cls._from_key(key)

    def public_der(self) -> bytes:
        """PublicKey.getEncoded: X.509 SubjectPublicKeyInfo (rsa.rs:516)."""
        return self.public._key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def decrypt(self, ciphertext) -> bytes:
        """RSAES-PKCS1-v1_5 расшифровка (rsa.rs:534, Crypt.decryptUsingKey).

        Считаем m = c^d mod n встроенным `pow` (не самописная RSA) и
        строго проверяем блок `00 02 FF.. 00 message`, как в rsa.rs.
        OpenSSL 3+ применяет implicit rejection (возвращает псевдослучайный
        результат вместо ошибки на плохом паддинге), поэтому проверку
        паддинга делаем сами — иначе поведение разошлось бы с Rust.
        """
        ct = _as_bytes(ciphertext)
        k = self.public.size()
        # rsa.rs:538 — ровно длина модуля и меньше самого модуля.
        if len(ct) != k or ct >= self.public.modulus:
            raise ProtocolError("Decryption error")
        numbers = self._key.private_numbers()
        n = numbers.public_numbers.n
        d = numbers.d
        block = pow(int.from_bytes(ct, "big"), d, n).to_bytes(k, "big")
        if block[0] != 0 or block[1] != 2:
            raise ProtocolError("Decryption error")
        zero = block.find(b"\x00", 2)
        if zero == -1 or zero < 10:
            raise ProtocolError("Decryption error")
        return block[zero + 1:]

    @classmethod
    def from_der(cls, der_bytes) -> "RsaPrivateKey":
        """PKCS8EncodedKeySpec или голый PKCS#1 RSAPrivateKey (rsa.rs:555)."""
        raw = _as_bytes(der_bytes)
        try:
            key = serialization.load_der_private_key(raw, password=None)
        except Exception as exc:  # noqa: BLE001
            raise ProtocolError("Malformed private key") from exc
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ProtocolError("Not an RSA private key")
        return cls._from_key(key)

    def sign(self, hash: SignatureHash, message) -> bytes:
        """RSASSA-PKCS1-v1_5 подпись (rsa.rs:611)."""
        try:
            signature = self._key.sign(
                _as_bytes(message),
                padding.PKCS1v15(),
                hash.algorithm,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProtocolError("RSA signing failed") from exc
        if not self.public.verify(hash, message, signature):
            raise ProtocolError("RSA signature failed its own check")
        return signature

    def verify(self, hash: SignatureHash, message, signature) -> bool:
        """Проверка подписи публичной частью этой пары."""
        return self.public.verify(hash, message, signature)


# Имя из задания: RsaKeyPair.
RsaKeyPair = RsaPrivateKey