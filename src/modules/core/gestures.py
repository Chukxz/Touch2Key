from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from modules.utils import Point, TouchEvent, TouchPhase


class GestureStatus(str, Enum):
    """Result of examining a touch event for a two-finger tap."""

    IDLE = "idle"
    PENDING = "pending"
    REJECTED = "rejected"
    RECOGNIZED = "recognized"


@dataclass(slots=True)
class GestureDecision:
    status: GestureStatus
    replay: tuple[TouchEvent, ...] = ()


@dataclass(slots=True)
class _Contact:
    origin: Point
    down_time: float
    last_position: Point
    up_time: float | None = None
    invalid: bool = False


@dataclass(slots=True)
class TwoFingerTapTracker:
    """Recognize a synchronized two-finger tap while buffering candidate input.

    ``observe`` is the engine-facing API. While a gesture is ambiguous, events
    are retained and returned only if the candidate is rejected. This prevents
    a delayed single-finger tap from leaking into menu actions before the
    gesture has been decided.

    ``process`` remains as a compatibility wrapper for older callers; new code
    should use ``observe`` so rejected events can be replayed.
    """

    max_tap_duration_s: float = 0.25
    max_drift_px: float = 25.0
    sync_window_s: float = 0.12

    _contacts: dict[int, _Contact] = field(default_factory=dict, init=False)
    _buffer: list[TouchEvent] = field(default_factory=list, init=False)
    _candidate_ids: set[int] = field(default_factory=set, init=False)
    _pending_since: float | None = field(default=None, init=False)
    _recognized: bool = field(default=False, init=False)

    @property
    def is_tracking(self) -> bool:
        """True while one or more contacts in the current candidate are down."""
        return any(c.up_time is None for c in self._contacts.values())

    @property
    def is_pending(self) -> bool:
        return bool(self._buffer) and not self._recognized

    def reset(self) -> None:
        self._contacts.clear()
        self._buffer.clear()
        self._candidate_ids.clear()
        self._pending_since = None
        self._recognized = False

    def _reject(self, extra: TouchEvent | None = None) -> GestureDecision:
        replay = list(self._buffer)
        if extra is not None:
            replay.append(extra)
        self.reset()
        return GestureDecision(GestureStatus.REJECTED, tuple(replay))

    def _valid_contact(self, contact: _Contact) -> bool:
        """Return whether a contact completed a valid tap."""
        up_time = contact.up_time
        if up_time is None or contact.invalid:
            return False
        return (
            0 <= up_time - contact.down_time <= self.max_tap_duration_s
            and (contact.last_position - contact.origin).magnitude <= self.max_drift_px
        )

    def _valid_pair(self) -> bool:
        if len(self._candidate_ids) != 2:
            return False

        contact_ids = tuple(self._candidate_ids)
        a = self._contacts.get(contact_ids[0])
        b = self._contacts.get(contact_ids[1])
        if a is None or b is None:
            return False

        # Validate each contact independently
        if not self._valid_contact(a) or not self._valid_contact(b):
            return False

        a_up_time = a.up_time
        b_up_time = b.up_time
        # _valid_contact has checked these, but explicit guards keep the types
        # narrowed locally for the release synchronization comparison.
        if a_up_time is None or b_up_time is None:
            return False

        if abs(a.down_time - b.down_time) > self.sync_window_s:
            return False
        if abs(a_up_time - b_up_time) > self.sync_window_s:
            return False
        return True

    def observe(self, event: TouchEvent) -> GestureDecision:
        """Examine an event and return whether it is pending, rejected or a tap.

        On rejection, ``replay`` contains all buffered candidate events in
        original order, including the event that caused rejection. The caller
        must send them through ordinary dispatch with gesture detection bypassed.
        """
        cid = event.contact_id
        phase = event.phase
        now = event.timestamp

        if not self._buffer:
            if phase is not TouchPhase.DOWN:
                return GestureDecision(GestureStatus.IDLE)
            self._contacts[cid] = _Contact(
                origin=event.position,
                down_time=now,
                last_position=event.position,
            )
            self._candidate_ids = {cid}
            self._pending_since = now
            self._buffer.append(event)
            return GestureDecision(GestureStatus.PENDING)

        # If a candidate is still unresolved but its joining window has elapsed,
        # replay it before treating this event as a new independent input.
        if (
            self._pending_since is not None
            and now - self._pending_since > self.sync_window_s
            and len(self._candidate_ids) < 2
            and cid not in self._candidate_ids
        ):
            return self._reject(event)

        if phase is TouchPhase.DOWN:
            if cid in self._contacts:
                return self._reject(event)  # duplicate DOWN / reused active ID
            if len(self._candidate_ids) >= 2:
                return self._reject(event)  # a third finger invalidates the tap
            first_down = min(c.down_time for c in self._contacts.values())
            if now - first_down > self.sync_window_s:
                return self._reject(event)
            self._contacts[cid] = _Contact(
                origin=event.position,
                down_time=now,
                last_position=event.position,
            )
            self._candidate_ids.add(cid)
            self._buffer.append(event)
            return GestureDecision(GestureStatus.PENDING)

        contact = self._contacts.get(cid)
        if contact is None or cid not in self._candidate_ids:
            # Unrelated contact activity invalidates ambiguity: do not swallow it.
            return self._reject(event)

        self._buffer.append(event)
        if phase is TouchPhase.MOVE:
            contact.last_position = event.position
            if (event.position - contact.origin).magnitude > self.max_drift_px:
                contact.invalid = True
                return self._reject()
            return GestureDecision(GestureStatus.PENDING)

        if phase is TouchPhase.UP:
            contact.last_position = event.position
            contact.up_time = now
            if (
                now < contact.down_time
                or now - contact.down_time > self.max_tap_duration_s
                or (event.position - contact.origin).magnitude > self.max_drift_px
            ):
                contact.invalid = True
                return self._reject()

            if len(self._candidate_ids) == 2 and all(
                self._contacts[c].up_time is not None for c in self._candidate_ids
            ):
                if self._valid_pair():
                    self.reset()
                    return GestureDecision(GestureStatus.RECOGNIZED)
                return self._reject()

            # Keep the candidate buffered after the first finger lifts: the
            # second finger may still arrive/release inside the synchronization
            # window.
            return GestureDecision(GestureStatus.PENDING)

        return GestureDecision(GestureStatus.PENDING)

    def process(self, event: TouchEvent) -> bool:
        """Compatibility wrapper; use ``observe`` when rejected events matter."""
        return self.observe(event).status is GestureStatus.RECOGNIZED

    def is_deferred(self, cid: int, current_time: float) -> bool:
        """Compatibility helper for callers using the previous tracker API."""
        return (
            self.is_pending
            and cid in self._candidate_ids
            and self._pending_since is not None
            and current_time - self._pending_since <= self.sync_window_s
        )
