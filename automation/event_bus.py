"""In-process asyncio pub/sub. Single publish/subscribe seam so a real broker can replace it later."""

import asyncio
from collections import defaultdict


class EventBus:
    def __init__(self) -> None:
        self._topics: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, topic: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._topics[topic].append(queue)
        return queue

    async def publish(self, topic: str, event: object) -> None:
        for queue in self._topics[topic]:
            queue.put_nowait(event)  # queues are unbounded, put_nowait never blocks
