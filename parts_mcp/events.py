"""In-memory EventStore for SSE resumability and priming events.

Enables priming events on SSE connections so they don't hang through
Cloudflare's response buffering. Also supports event replay for clients
that reconnect with a Last-Event-ID header.
"""
import logging
import threading
from collections import defaultdict

from mcp.server.streamable_http import EventCallback, EventId, EventStore, StreamId
from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)

# Cap stored events per stream to bound memory usage.
MAX_EVENTS_PER_STREAM = 500


class InMemoryEventStore(EventStore):
    """Simple in-memory event store for single-process deployments."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        # stream_id -> [(event_id, message)]
        self._streams: dict[StreamId, list[tuple[EventId, JSONRPCMessage | None]]] = defaultdict(list)

    async def store_event(
        self, stream_id: StreamId, message: JSONRPCMessage | None
    ) -> EventId:
        with self._lock:
            self._counter += 1
            event_id = str(self._counter)
            events = self._streams[stream_id]
            events.append((event_id, message))
            # Evict oldest events if over limit
            if len(events) > MAX_EVENTS_PER_STREAM:
                self._streams[stream_id] = events[-MAX_EVENTS_PER_STREAM:]
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        with self._lock:
            # Find the stream containing this event ID
            for stream_id, events in self._streams.items():
                for i, (eid, _msg) in enumerate(events):
                    if eid == last_event_id:
                        # Replay everything after this event
                        to_replay = events[i + 1:]
                        break
                else:
                    continue
                # Found the stream, replay events
                for eid, msg in to_replay:
                    if msg is not None:
                        await send_callback(eid, msg)
                return stream_id
        return None
