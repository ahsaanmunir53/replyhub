"""Rotating SECRET_KEY: secrets sealed with the old key still open until they are resealed."""

from __future__ import annotations

import pytest

from chatfront.core.errors import AppError
from chatfront.core.secretbox import remember_previous, seal, unseal

OLD, NEW = "old-key-" + "x" * 32, "new-key-" + "y" * 32


def test_the_previous_key_still_opens_during_a_rotation() -> None:
    sealed = seal("shpat_token", OLD)
    with pytest.raises(AppError):
        unseal(sealed, NEW)
    remember_previous([OLD])
    try:
        assert unseal(sealed, NEW) == "shpat_token"
        assert unseal(seal("again", NEW), NEW) == "again"
    finally:
        remember_previous([])
    with pytest.raises(AppError):
        unseal(sealed, NEW)
