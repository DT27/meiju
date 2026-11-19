# -*- coding: utf-8 -*-
"""AES / 8370 / cloud signing, based on msmart + hasscc/meiju."""

from __future__ import print_function

import hmac
import logging
import os
import urllib.parse
from hashlib import md5, sha256
from urllib.parse import urlparse

from .const import MSGTYPE_ENCRYPTED_REQUEST, MSGTYPE_ENCRYPTED_RESPONSE

_LOGGER = logging.getLogger(__name__)

try:
    from Crypto.Cipher import AES as _CryptoAES
except ImportError:
    try:
        from Cryptodome.Cipher import AES as _CryptoAES
    except ImportError:
        _CryptoAES = None

from . import _pyaes


class _AesCipher(object):
    """pycryptodome-compatible ECB/CBC wrapper, with pure-Python fallback."""

    MODE_ECB = 1
    MODE_CBC = 2

    def __init__(self, key, mode, iv=None):
        self._key = bytes(key)
        self._mode = mode
        self._iv = bytes(iv) if iv is not None else None
        if _CryptoAES is not None:
            if mode == self.MODE_ECB:
                self._impl = _CryptoAES.new(self._key, _CryptoAES.MODE_ECB)
            else:
                self._impl = _CryptoAES.new(self._key, _CryptoAES.MODE_CBC, iv=self._iv)
            self._fallback = False
        else:
            self._fallback = True
            self._impl = None

    def encrypt(self, data):
        data = bytes(data)
        if not self._fallback:
            return self._impl.encrypt(data)
        return _block_crypt(data, self._key, self._iv, True, self._mode == self.MODE_CBC)

    def decrypt(self, data):
        data = bytes(data)
        if not self._fallback:
            return self._impl.decrypt(data)
        return _block_crypt(data, self._key, self._iv, False, self._mode == self.MODE_CBC)


class AES(object):
    MODE_ECB = _AesCipher.MODE_ECB
    MODE_CBC = _AesCipher.MODE_CBC

    @staticmethod
    def new(key, mode, iv=None):
        return _AesCipher(key, mode, iv=iv)


def _block_crypt(data, key, iv, encrypt, cbc):
    if len(data) % 16:
        raise ValueError('AES data length must be a multiple of 16')
    if cbc:
        cipher = _pyaes.AESModeOfOperationCBC(key, iv=iv or (b'\0' * 16))
    else:
        cipher = _pyaes.AESModeOfOperationECB(key)
    out = bytearray()
    op = cipher.encrypt if encrypt else cipher.decrypt
    for i in range(0, len(data), 16):
        out.extend(op(data[i:i + 16]))
    return bytes(out)

APP_KEY = '434a209a5ce141c3b726de067835d7f0'
SIGN_KEY = 'xhdiwjnchekd4d512chdjx5d8e4c394D2D7S'
HMAC_KEY = 'PROD_VnoClJI9aikS8dyy'
DEFAULT_DATA_KEY = '96c7acdfdb8af79a'

LOGIN_KEY_GLOBAL = 'ac21b9f9cbfe4ca5a88562ef25e2b768'
LOGIN_KEY_CHINA = 'ad0ee21d48a64bf49f4fb583ab76e799'
IOTKEY_GLOBAL = 'meicloud'
IOTKEY_CHINA = 'prod_secret123@muc'

BLOCK_SIZE = 16


def _pad(data, block=BLOCK_SIZE):
    if isinstance(data, bytearray):
        data = bytes(data)
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _unpad(data, block=BLOCK_SIZE):
    if not data:
        return data
    n = data[-1]
    if n < 1 or n > block:
        return data
    return data[:-n]


def strxor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


class MeijuSecurity(object):
    def __init__(self, use_china_server=False):
        self.appKey = APP_KEY.encode()
        self.signKey = SIGN_KEY.encode()
        self.blockSize = BLOCK_SIZE
        self.iv = b'\0' * 16
        self.encKey = md5(self.signKey).digest()
        self.dynamicKey = md5(self.appKey).digest()[:8]
        self._tcp_key = None
        self._request_count = 0
        self._response_count = 0
        self._hmackey = HMAC_KEY
        self._use_china_server = use_china_server
        if use_china_server:
            self._iotkey = IOTKEY_CHINA
            self._loginKey = LOGIN_KEY_CHINA
        else:
            self._iotkey = IOTKEY_GLOBAL
            self._loginKey = LOGIN_KEY_GLOBAL

    def aes_decrypt(self, raw):
        cipher = AES.new(self.encKey, AES.MODE_ECB)
        try:
            decrypted = cipher.decrypt(bytes(raw))
            return _unpad(decrypted, self.blockSize)
        except ValueError as exc:
            _LOGGER.error('aes_decrypt error: %s - data: %s', repr(exc), getattr(raw, 'hex', lambda: raw)())
            return bytearray(0)

    def aes_encrypt(self, raw):
        raw = _pad(raw, self.blockSize)
        cipher = AES.new(self.encKey, AES.MODE_ECB)
        return cipher.encrypt(bytes(raw))

    def aes_cbc_decrypt(self, raw, key):
        return AES.new(key, AES.MODE_CBC, iv=self.iv).decrypt(raw)

    def aes_cbc_encrypt(self, raw, key):
        return AES.new(key, AES.MODE_CBC, iv=self.iv).encrypt(raw)

    def encode32_data(self, raw):
        return md5(bytes(raw) + self.signKey).digest()

    def tcp_key(self, response, key):
        if response == b'ERROR':
            _LOGGER.error('authentication failed')
            return b'', False
        if len(response) != 64:
            _LOGGER.error('unexpected data length: %s', len(response))
            return b'', False
        payload = response[:32]
        sign = response[32:]
        plain = self.aes_cbc_decrypt(payload, key)
        if sha256(plain).digest() != sign:
            _LOGGER.error('sign does not match')
            return b'', False
        self._tcp_key = strxor(plain, key)
        self._request_count = 0
        self._response_count = 0
        return self._tcp_key, True

    def encode_8370(self, data, msgtype):
        header = bytes([0x83, 0x70])
        size, padding = len(data), 0
        if msgtype in (MSGTYPE_ENCRYPTED_RESPONSE, MSGTYPE_ENCRYPTED_REQUEST):
            if (size + 2) % 16 != 0:
                padding = 16 - (size + 2 & 0xf)
                size += padding + 32
                data += os.urandom(padding)
        header += size.to_bytes(2, 'big')
        header += bytes([0x20, padding << 4 | msgtype])
        if self._request_count >= 0xfff:
            self._request_count = 0
        data = self._request_count.to_bytes(2, 'big') + data
        self._request_count += 1
        if msgtype in (MSGTYPE_ENCRYPTED_RESPONSE, MSGTYPE_ENCRYPTED_REQUEST):
            sign = sha256(header + data).digest()
            data = self.aes_cbc_encrypt(data, self._tcp_key) + sign
        return header + data

    def decode_8370(self, data):
        if len(data) < 6:
            return [], data
        header = data[:6]
        if header[0] != 0x83 or header[1] != 0x70:
            raise Exception('not an 8370 message')
        size = int.from_bytes(header[2:4], 'big') + 8
        leftover = None
        if len(data) < size:
            return [], data
        if len(data) > size:
            leftover = data[size:]
            data = data[:size]
        if header[4] != 0x20:
            raise Exception('missing byte 4')
        padding = header[5] >> 4
        msgtype = header[5] & 0xf
        data = data[6:]
        if msgtype in (MSGTYPE_ENCRYPTED_RESPONSE, MSGTYPE_ENCRYPTED_REQUEST):
            sign = data[-32:]
            data = data[:-32]
            data = self.aes_cbc_decrypt(data, self._tcp_key)
            if sha256(header + data).digest() != sign:
                raise Exception('sign does not match')
            if padding:
                data = data[:-padding]
        self._response_count = int.from_bytes(data[:2], 'big')
        data = data[2:]
        if leftover:
            packets, incomplete = self.decode_8370(leftover)
            return [data] + packets, incomplete
        return [data], b''

    def sign(self, url, payload):
        path = urlparse(url).path
        query = sorted(payload.items(), key=lambda x: x[0])
        query = urllib.parse.unquote_plus(urllib.parse.urlencode(query))
        sign = path + query + self._loginKey
        return sha256(sign.encode('ASCII')).hexdigest()

    def new_sign(self, data, random):
        msg = self._iotkey
        if data:
            msg += data
        msg += random
        return hmac.new(
            self._hmackey.encode('ascii'),
            msg.encode('ascii'),
            sha256,
        ).hexdigest()

    def encryptPassword(self, login_id, password):
        hashed = sha256(password.encode('ascii')).hexdigest()
        login_hash = login_id + hashed + self._loginKey
        return sha256(login_hash.encode('ascii')).hexdigest()

    def encrypt_iam_password(self, login_id, password):
        first = md5(password.encode('ascii')).hexdigest()
        second = md5(first.encode('ascii')).hexdigest()
        if self._use_china_server:
            return second
        login_hash = login_id + second + self._loginKey
        return sha256(login_hash.encode('ascii')).hexdigest()

    def decrypt_with_key(self, data, key=DEFAULT_DATA_KEY):
        if isinstance(data, str):
            data = bytes.fromhex(data)
        if isinstance(key, str):
            key = key.encode()
        return _unpad(AES.new(key, AES.MODE_ECB).decrypt(data), self.blockSize).decode()

    def encrypt_with_key(self, data, key=DEFAULT_DATA_KEY):
        if isinstance(data, str):
            data = bytes.fromhex(data)
        if isinstance(key, str):
            key = key.encode()
        return AES.new(key, AES.MODE_ECB).encrypt(_pad(data, self.blockSize))


def get_udpid(data):
    digest = sha256(data).digest()
    b1, b2 = digest[:16], digest[16:]
    return bytes(x ^ y for x, y in zip(b1, b2)).hex()
