"""Encrypt per-tenant secrets (channel access tokens, store keys) before they reach the database.

Rotating SECRET_KEY: set the new key as SECRET_KEY and the old one as SECRET_KEY_PREVIOUS,
deploy, then run `python -m chatfront.core.reseal` once. Every stored secret is then sealed
with the new key, and SECRET_KEY_PREVIOUS can be removed. Until then, secrets sealed with the
old key still open. (Console sign-in links signed with the old key stop working at once.)
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from chatfront.core.errors import AppError


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(("chatfront-secretbox:" + secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plaintext: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode()).decode()


_previous: list[str] = []  # SECRET_KEY_PREVIOUS while a rotation is under way


def remember_previous(keys: list[str]) -> None:
    _previous[:] = [k for k in keys if k]


def unseal(token: str, secret_key: str) -> str:
    for key in (secret_key, *_previous):
        try:
            return _fernet(key).decrypt(token.encode()).decode()
        except InvalidToken:
            continue
    raise AppError("secret_unreadable", "A stored secret could not be decrypted")
