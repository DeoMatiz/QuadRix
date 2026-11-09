#!/usr/bin/env python3
"""Тесты quadrix/protocol/crypto.py.

Порт horizon-protocol/src/crypto.rs и rsa.rs. Проверяются точные
байты из тестов Rust (NIST SP 800-38A, FIPS-197, вектор OpenSSL,
server hash Notch/jeb_/simon) и round-trip AES/CFB8 + RSA.

crypto.rs/rsa.rs не читают файлов из `.local` (это чистый код
провода и ключи, встроенные константами Rust), поэтому тестов с
реальными данными `.local` здесь нет — как и в test_buf.py,
загружать нечего. Векторы взяты из `#[cfg(test)]` Rust один в один.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from quadrix.protocol.buf import ProtocolError
from quadrix.protocol.crypto import (
    Cfb8,
    CFB8Decryptor,
    CFB8Encryptor,
    Cipher,
    E,
    MinecraftCipher,
    RsaKeyPair,
    RsaPrivateKey,
    RsaPublicKey,
    SignatureHash,
    generate_secret,
    java_hex_digest,
    md5,
    offline_uuid,
    random_bytes,
    server_hash,
    uuid_string,
)


def h(s: str) -> bytes:
    """Hex-строка → bytes (как `hex` в тестах Rust: нечётная длина паддится)."""
    if len(s) % 2 == 1:
        s = "0" + s
    return bytes.fromhex(s)


# ── Векторы из rsa.rs::tests ─────────────────────────────────────────

# 1024-битный ключ `openssl genrsa 1024` (rsa.rs:640).
TEST_SPKI = (
    "30819f300d06092a864886f70d010101050003818d0030818902818100ab026074f92450a8f726f3"
    "895bb11176ca8f065f3100cd4143bac4f7d3674edcff95b41a0525d2365a549c106ec6685881b3"
    "92177420fd31ff5c144ff11ba24311e751cd2c6b5d1817b6af6686a43c95d61243613005e6945b"
    "6093cd95223cec5e8856826da9d2ee1b323362ac1cebeab3659cbc45319a9b540dda816a4798ff"
    "0203010001"
)
TEST_N = (
    "ab026074f92450a8f726f3895bb11176ca8f065f3100cd4143bac4f7d3674edcff95b41a0525d236"
    "5a549c106ec6685881b392177420fd31ff5c144ff11ba24311e751cd2c6b5d1817b6af6686a43c"
    "95d61243613005e6945b6093cd95223cec5e8856826da9d2ee1b323362ac1cebeab3659cbc4531"
    "9a9b540dda816a4798ff"
)
TEST_SIG_HELLO = (
    "0bc8716622e44f9bf72432045e91bf1b40a96aae3c402fa86262b83758db1c90d2ed16b9fa86f29"
    "af175f2e6eedb864bf8da2667a7ada2bf5433fba36c1951af0c356e45bd5f90fb905b9a08f33a0"
    "666c4968ccffbf32fda643d736deec66f82c75fe4a8075c7f2b8a6c0ca630e0ffe4805a1f1d672"
    "506b82fc188510fb4ef80"
)

# 1024-битный PKCS#8 и его публичная половина (rsa.rs:783–785).
PKCS8 = (
    "30820275020100300d06092a864886f70d01010105000482025f3082025b02010002818100a483a9"
    "a2ce1762edb78b7359b96415e35885db2cebb0615d36ce314623a5c3ddb5fe1dccdb6066c4dfe1"
    "6125baf73ca48b4658285da6adf1ccf0bd18be0f67e3a1d68e9547fc129b6d3fe74413ed5f9871"
    "23f556b54a8c3a434a0fd4a02d4599d73fbdbf403bc229ed3c6e45877fbb2a20fd3850f1a19c5a"
    "dbefb703eac785eb02030100010281803e646cb68100df9516523dea1e6475e4a61305ffb05751"
    "65bfbe4d73b35b4fc04b2057fef48848118c72f69c0f9f6a9160fcc9bc6d6024821ade8668d6d4"
    "12eae70f2c19d1890877c4fe46aebbbf2324ad3f304dfc7bd6ec484befe4730cc72c749a557c0d"
    "0bb6a73093ef571e4fc543ff5a5ec146e9799ca98f9a71b6c08831024100d5e071afe69c04174e"
    "ea3023c16a3226a577a3ae01c0166ce68dac20791c75aec47ee115ab52a86ae0a7860ba87bfb6f"
    "37a8754d72feec7073eff4d6485dd2b3024100c4ea63df21d6711e15a431400a84c127acb6a77c"
    "22f475fc807be941a6a80fc0edd4bab09f09a157e517580777c2caf832e5fa07375fc8f3f1286e"
    "9f9e9ebbe90240609199e37975a2673fcb7ff6f502d5281bf83c207a4bd8144db95429c9656f41"
    "7d1968da16e4188541708296caf9481afc7f848f76c7e1cc189d14e897fe3cff024043ba4e8177"
    "74f7511ea66b9e184012e35f7f2f59fdf7d100f8fc257d4421f7d126bc0d3e24653e8e29a87ec9"
    "8ac27fe72032836da9f912f7fc5128c353de4ac902401a16b013e8717963d6f938b0126db15eec"
    "c678ccd0b3b8497aa6528d522f89087112694fd5082b9838ba162de4831589195284a6aa24711f"
    "c7d54ec073dfddf1"
)
PKCS8_SPKI = (
    "30819f300d06092a864886f70d010101050003818d0030818902818100a483a9a2ce1762edb78b73"
    "59b96415e35885db2cebb0615d36ce314623a5c3ddb5fe1dccdb6066c4dfe16125baf73ca48b46"
    "58285da6adf1ccf0bd18be0f67e3a1d68e9547fc129b6d3fe74413ed5f987123f556b54a8c3a43"
    "4a0fd4a02d4599d73fbdbf403bc229ed3c6e45877fbb2a20fd3850f1a19c5adbefb703eac785eb"
    "0203010001"
)
PKCS8_SIG_CHAT = (
    "3a6ed84b109a293d92a53b2120925f3fa33d3b81b686e9a9f0f1f935bd80a263b0912cf0bcd5ac"
    "5ca14ffcd3301a23cb2c3d828a092bb49cc8831a3c1f9be674a44a7c906dd8d48e00edcf7c899a"
    "75b19e2eea6d94f868507005448692f8c500192268a286988a025c09ad8fa99ffb50de52c2e892"
    "310111c22cdb8b3ac4eb8a"
)


# ── AES/CFB8 ─────────────────────────────────────────────────────────

def test_cfb8_nist_sp800_38a_vector_and_state():
    """crypto.rs:201 — вектор NIST, разбитый на два вызова encrypt."""
    key = h("2b7e151628aed2a6abf7158809cf4f3c")
    iv = h("000102030405060708090a0b0c0d0e0f")
    plain = h("6bc1bee22e409f96e93d7e117393172aae2d")
    expected = h("3b79424c9c0dd436bace9e0ed4586a4f32b9")

    enc = Cfb8(key, iv)
    # Потоковый шифр: два вызова подряд дают то же, что один.
    got = enc.encrypt(plain[:5]) + enc.encrypt(plain[5:])
    assert got == expected

    dec = Cfb8(key, iv)
    assert dec.decrypt(got) == plain


def test_cfb8_round_trip_random_32_bytes():
    """32 случайных байта: encrypt + decrypt → исходные."""
    key = os.urandom(16)
    iv = os.urandom(16)
    plain = os.urandom(32)
    cipher = Cfb8(key, iv).encrypt(plain)
    assert cipher != plain
    assert len(cipher) == 32
    assert Cfb8(key, iv).decrypt(cipher) == plain


def test_cfb8_stateful_concat_equals_single_call():
    """Два encrypt на разных буферах == один на конкатенации."""
    key = os.urandom(16)
    iv = os.urandom(16)
    data = os.urandom(96)

    once = Cfb8(key, iv).encrypt(data)

    stream = Cfb8(key, iv)
    parts = b""
    for cut in (1, 7, 8, 15, 16, 17, 32):
        parts += stream.encrypt(data[:cut])
        data = data[cut:]
    parts += stream.encrypt(data)
    assert parts == once


def test_cfb8_decrypt_over_arbitrary_cuts():
    """Расшифровка любыми кусками даёт исходник (crypto.rs:252)."""
    key = os.urandom(16)
    iv = os.urandom(16)
    plain = os.urandom(5000)
    cipher = Cfb8(key, iv).encrypt(plain)

    for cuts in ([5000], [1, 7, 8, 9, 15, 16, 17, 1000, 3927], [3, 4997]):
        dec = Cfb8(key, iv)
        out = b""
        offset = 0
        for n in cuts:
            out += dec.decrypt(cipher[offset:offset + n])
            offset += n
        assert out == plain


def test_cfb8_encryptor_decryptor_wrappers():
    key = os.urandom(16)
    iv = os.urandom(16)
    msg = os.urandom(48)
    enc = CFB8Encryptor(key, iv)
    cipher = enc.update(msg[:20]) + enc.update(msg[20:])
    dec = CFB8Decryptor(key, iv)
    assert dec.update(cipher) == msg


def test_cfb8_rejects_wrong_key_or_iv_size():
    with pytest.raises(ProtocolError):
        Cfb8(b"short", b"0123456789abcdef")
    with pytest.raises(ProtocolError):
        Cfb8(b"0123456789abcdef", b"short")


def test_minecraft_cipher_round_trip():
    secret = os.urandom(16)
    msg = os.urandom(64)
    c = MinecraftCipher(secret)
    cipher = c.encrypt(msg)
    other = Cipher(secret)
    assert other.decrypt(cipher) == msg
    assert c.secret == secret


# ── Случайность ──────────────────────────────────────────────────────

def test_random_and_secret():
    a = generate_secret()
    b = generate_secret()
    assert len(a) == 16 and len(b) == 16
    assert a != b
    assert len(random_bytes(33)) == 33


# ── Java-хэши / UUID ─────────────────────────────────────────────────

def test_java_hex_digest_vectors():
    """crypto.rs:291 — знаковое шестнадцатеричное представление."""
    assert java_hex_digest(h("4ed1f46bbe04bc756bcb17c0c7ce3e4632f06a48")) == (
        "4ed1f46bbe04bc756bcb17c0c7ce3e4632f06a48"
    )
    assert java_hex_digest(b"\x00\x00\x00\x00") == "0"
    assert java_hex_digest(b"\xff\xff") == "-1"
    assert java_hex_digest(b"\x80\x00") == "-8000"


def test_server_hash_vectors():
    """crypto.rs:291 — дайджесты имён из документации протокола."""
    assert server_hash("", b"Not", b"ch") == (
        "4ed1f46bbe04bc756bcb17c0c7ce3e4632f06a48"
    )
    assert server_hash("", b"jeb_", b"") == (
        "-7c9d5b0044c130109a5d7b5fb5c317c02b4e28c1"
    )
    assert server_hash("", b"simon", b"") == (
        "88e16a1019277b15d58faf0541e11910eb756f6"
    )
    # Три входа хэшируются по порядку: один update == три.
    assert server_hash("", b"Not", b"ch") == java_hex_digest(
        hashlib.sha1(b"Notch").digest()
    )


def test_md5_and_offline_uuids():
    """crypto.rs:311 — MD5 и UUID.nameUUIDFromBytes."""
    assert md5(b"") == h("d41d8cd98f00b204e9800998ecf8427e")
    assert md5(b"abc") == h("900150983cd24fb0d6963f7d28e17f72")
    assert md5(b"a" * 100) == h("36a92cc94a9e0fa21f625f8bfb007adf")
    assert uuid_string(offline_uuid("Notch")) == (
        "b50ad385-829d-3141-a216-7e7d7539ba7f"
    )


# ── RSA ──────────────────────────────────────────────────────────────

def test_rsa_public_parses_test_key():
    """rsa.rs:660 — поля X.509 ключа и размер."""
    key = RsaPublicKey.from_der(h(TEST_SPKI))
    assert key.modulus == h(TEST_N)
    assert key.exponent == b"\x01\x00\x01"
    assert key.exponent == E.to_bytes(3, "big")
    assert key.size() == 128
    with pytest.raises(ProtocolError):
        RsaPublicKey.from_der(h(TEST_SPKI)[:100])
    with pytest.raises(ProtocolError):
        RsaPublicKey.from_der(b"not a key")


def test_rsa_pkcs1_round_trip_with_known_key():
    """rsa.rs:672 — encrypt 16 байт публичным, decrypt приватным.

    Приватная часть TEST_SPKI в rsa.rs задана одним числом d и
    восстанавливается только «сырым» m^d mod n; полноценно загрузить
    такую пару `cryptography` не может (нет CRT-полей). Поэтому для
    известного ключа берём полный PKCS#8 (rsa.rs:783) — его публичная
    половина даёт тот же 128-байтовый шифртекст.
    """
    private = RsaPrivateKey.from_der(h(PKCS8))
    secret = b"\x5a" * 16
    a = private.public.encrypt(secret)
    b = private.public.encrypt(secret)
    assert len(a) == 128
    assert a != b, "паддинг случайный"
    assert private.decrypt(a) == secret
    assert private.decrypt(b) == secret
    # Сообщение длиной 128 - 11 уже не влезает.
    with pytest.raises(ProtocolError):
        private.public.encrypt(b"\x00" * 118)


def test_rsa_generate_round_trip():
    """rsa.rs:692 — generate → encrypt → decrypt."""
    key = RsaPrivateKey.generate(1024)
    assert key.public.size() == 128
    assert key.public.exponent == b"\x01\x00\x01"
    for message in (b"\x5a" * 16, b"\x01\x02\x03\x04", b""):
        cipher = key.public.encrypt(message)
        assert key.decrypt(cipher) == message
    with pytest.raises(ProtocolError):
        key.decrypt(b"\x00" * 128)
    with pytest.raises(ProtocolError):
        key.decrypt(b"\x01" * 64)


def test_rsa_generated_public_der_round_trip():
    """rsa.rs:692 — public_der разбирается обратно в тот же ключ."""
    key = RsaKeyPair.generate(1024)
    der = key.public_der()
    assert der[:3] == b"\x30\x81\x9f", "1024-битный SubjectPublicKeyInfo"
    parsed = RsaPublicKey.from_der(der)
    assert parsed.modulus == key.public.modulus
    assert parsed.exponent == key.public.exponent


def test_rsa_pkcs8_matches_openssl_and_signs_like_it():
    """rsa.rs:789 — PKCS#8 читается, public_der == OpenSSL, подпись та же."""
    key = RsaPrivateKey.from_der(h(PKCS8))
    assert key.public.modulus == RsaPublicKey.from_der(h(PKCS8_SPKI)).modulus
    assert key.public_der() == h(PKCS8_SPKI)

    signature = key.sign(SignatureHash.Sha256, b"chat")
    # PKCS#1 v1.5 детерминирован: байты обязаны совпасть с OpenSSL.
    assert signature == h(PKCS8_SIG_CHAT)
    assert key.public.verify(SignatureHash.Sha256, b"chat", signature)

    with pytest.raises(ProtocolError):
        RsaPrivateKey.from_der(h(PKCS8)[:200])
    with pytest.raises(ProtocolError):
        RsaPrivateKey.from_der(h(PKCS8_SPKI))
    with pytest.raises(ProtocolError):
        RsaPrivateKey.from_der(b"not a key")


def test_rsa_verify_openssl_signature():
    """rsa.rs:736 — подпись OpenSSL SHA256withRSA проходит проверку."""
    key = RsaPublicKey.from_der(h(TEST_SPKI))
    signature = h(TEST_SIG_HELLO)
    assert key.verify(SignatureHash.Sha256, b"hello", signature)
    assert not key.verify(SignatureHash.Sha256, b"hellO", signature)
    assert not key.verify(SignatureHash.Sha1, b"hello", signature)
    flipped = bytearray(signature)
    flipped[40] ^= 1
    assert not key.verify(SignatureHash.Sha256, b"hello", bytes(flipped))
    assert not key.verify(SignatureHash.Sha256, b"hello", signature[1:])
    assert not key.verify(SignatureHash.Sha256, b"hello", key.modulus)


def test_rsa_generated_signs_both_digests():
    key = RsaPrivateKey.generate(1024)
    for hash in (SignatureHash.Sha1, SignatureHash.Sha256):
        signature = key.sign(hash, b"message")
        assert len(signature) == 128
        assert key.public.verify(hash, b"message", signature)
        assert not key.public.verify(hash, b"messagE", signature)