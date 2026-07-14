import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    name: str
    payload: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)


Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.subscribers: list[Subscriber] = []
        self.recent: deque[Event] = deque(maxlen=200)

    def subscribe(self, subscriber: Subscriber) -> None:
        self.subscribers.append(subscriber)

    def publish(self, event: Event) -> None:
        if not self.enabled:
            return
        self.recent.append(event)
        for subscriber in self.subscribers:
            subscriber(event)
