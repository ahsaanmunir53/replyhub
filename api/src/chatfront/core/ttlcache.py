"""A small in-process cache for public pages that many visitors open at once.

A shop's page and product list change rarely, but each one costs several database round trips;
on a database far from the server that is seconds. Kept for a few seconds per worker, a busy
shop page then costs one load, not one per visitor. Off (0 seconds) unless set, so tests and
owners editing their shop see changes at once.
"""

from __future__ import annotations

import time
from collections import OrderedDict


class TtlCache[T]:
    def __init__(self, size: int = 512) -> None:
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._size = size

    def get(self, key: str, seconds: float) -> T | None:
        found = self._items.get(key)
        if found is None or seconds <= 0 or time.monotonic() - found[0] > seconds:
            return None
        return found[1]

    def put(self, key: str, value: T, seconds: float) -> None:
        if seconds <= 0:
            return
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)
