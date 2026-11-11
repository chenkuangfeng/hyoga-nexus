"""WeCom callback signature and AES envelope (official 加解密方案, checked 2026-11-12).

- ``msg_signature = sha1(sorted(token, timestamp, nonce, msg_encrypt) joined)`` in lowercase hex.
- ``AESKey = base64decode(EncodingAESKey + '=')`` (32 bytes), AES-256-CBC, IV = the key's first 16 bytes,
  PKCS#7 padding to a multiple of 32 bytes.
- Plaintext = 16 random bytes + 4-byte big-endian length + message + receive id (the corp id for corp apps).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BLOCK = 32


class CallbackError(Exception):
    """The callback is not authentic or not addressed to this corp."""


def signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    return hashlib.sha1(''.join(sorted([token, timestamp, nonce, encrypted])).encode()).hexdigest()


class CallbackCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise CallbackError('EncodingAESKey must have 43 characters')
        self.token, self.receive_id = token, receive_id
        self.key = base64.b64decode(encoding_aes_key + '=')

    def decrypt(self, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> str:
        """Verify the signature, decrypt and check the receive id; return the message text."""
        expected = signature(self.token, timestamp, nonce, encrypted)
        if not hmac.compare_digest(expected, msg_signature or ''):
            raise CallbackError('bad signature')
        try:
            data = base64.b64decode(encrypted)
            decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).decryptor()
            plain = decryptor.update(data) + decryptor.finalize()
            pad = plain[-1]
            if not 1 <= pad <= BLOCK:
                raise ValueError('padding')
            plain = plain[:-pad]
            (length,) = struct.unpack('>I', plain[16:20])
            message, receive_id = plain[20:20 + length], plain[20 + length:]
        except (ValueError, struct.error) as exc:
            raise CallbackError('cannot decrypt') from exc
        if receive_id.decode('utf-8', 'replace') != self.receive_id:
            raise CallbackError('message is for another receiver')
        return message.decode('utf-8')

    def encrypt(self, message: str, timestamp: str, nonce: str) -> tuple[str, str]:
        """Return ``(encrypted, msg_signature)`` for a reply; also used by tests to build callbacks."""
        body = message.encode('utf-8')
        plain = os.urandom(16) + struct.pack('>I', len(body)) + body + self.receive_id.encode('utf-8')
        pad = BLOCK - len(plain) % BLOCK
        plain += bytes([pad]) * pad
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).encryptor()
        encrypted = base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode()
        return encrypted, signature(self.token, timestamp, nonce, encrypted)
