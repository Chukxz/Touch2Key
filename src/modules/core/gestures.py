from __future__ import annotations

from dataclasses import dataclass, field

from modules.utils import Point, TouchEvent, TouchPhase


@dataclass(slots=True)
class TwoFingerTapTracker:
    """Detects strict, stationary, synchronized two-finger taps."""

    max_tap_duration_s: float = 0.25
    max_drift_px: float = 25.0
    sync_window_s: float = 0.12

    _contacts: dict[int, tuple[Point, float]] = field(default_factory=dict, init=False)
    _active_contacts: set[int] = field(default_factory=set, init=False)
    _release_times: dict[int, float] = field(default_factory=dict, init=False)
    _invalidated: bool = field(default=False, init=False)

    @property
    def is_tracking(self) -> bool:
        """Whether any participating contact is still down."""
        return bool(self._active_contacts)

    def reset(self) -> None:
        self._contacts.clear()
        self._active_contacts.clear()
        self._release_times.clear()
        self._invalidated = False

    def process(self, event: TouchEvent) -> bool:
        cid = event.contact_id
        phase = event.phase
        pos = event.position
        now = event.timestamp

        if phase is TouchPhase.DOWN:
            # Duplicate DOWN for an already-active contact is invalid.
            if cid in self._active_contacts:
                self._invalidated = True
                return False

            # Track every new contact so invalid gestures can be cleaned up.
            if cid in self._contacts:
                # A contact ID was reused before this gesture finished.
                self._invalidated = True
                self._active_contacts.add(cid)
                return False

            if self._invalidated:
                self._contacts[cid] = (pos, now)
                self._active_contacts.add(cid)
                return False

            self._contacts[cid] = (pos, now)
            self._active_contacts.add(cid)

            # A third contact invalidates the gesture.
            if len(self._contacts) > 2:
                self._invalidated = True
                return False

            # The two DOWN events must be synchronized.
            if len(self._contacts) == 2:
                start_times = [start for _, start in self._contacts.values()]
                if max(start_times) - min(start_times) > self.sync_window_s:
                    self._invalidated = True

            return False

        if phase is TouchPhase.MOVE:
            if cid not in self._active_contacts or self._invalidated:
                return False

            origin_pos, _ = self._contacts[cid]
            if (pos - origin_pos).magnitude > self.max_drift_px:
                self._invalidated = True

            return False

        if phase is TouchPhase.UP:
            if cid not in self._active_contacts:
                return False

            if self._invalidated:
                self._active_contacts.remove(cid)
                if not self._active_contacts:
                    self.reset()
                return False

            origin_pos, start_time = self._contacts[cid]
            duration = now - start_time
            drift = (pos - origin_pos).magnitude

            self._active_contacts.remove(cid)

            if (
                duration < 0
                or duration > self.max_tap_duration_s
                or drift > self.max_drift_px
            ):
                self._invalidated = True
                if not self._active_contacts:
                    self.reset()
                return False

            self._release_times[cid] = now

            # Wait until both original contacts have released.
            if len(self._release_times) == 2:
                release_times = list(self._release_times.values())
                synchronized = (
                    max(release_times) - min(release_times) <= self.sync_window_s
                )
                valid = synchronized and not self._active_contacts
                self.reset()
                return valid

            # One finger tapped alone; don't wait for a later second finger.
            if not self._active_contacts:
                self.reset()

            return False

        return False
