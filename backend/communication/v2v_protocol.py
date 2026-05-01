from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import time
from typing import Callable, Dict, Tuple


@dataclass(frozen=True, slots=True)
class V2VMessage:
    truck_id: str
    position: Dict[str, float]
    state: str
    reserved_cells: Tuple[Tuple[int, int], ...]
    eta: float
    timestamp: float = field(default_factory=time)


Subscriber = Callable[[V2VMessage], None]


class InMemoryV2VProtocol:
    def __init__(self) -> None:
        self._subscribers: Dict[int, Subscriber] = {}
        self._next_token = 1
        self._lock = Lock()

    def subscribe(self, subscriber: Subscriber) -> int:
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = subscriber
            return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def publish(self, message: V2VMessage) -> None:
        with self._lock:
            subscribers = list(self._subscribers.values())

        for subscriber in subscribers:
            subscriber(message)

    def reset(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._next_token = 1


DEFAULT_V2V_PROTOCOL = InMemoryV2VProtocol()
