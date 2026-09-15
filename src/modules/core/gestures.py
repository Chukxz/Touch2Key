from __future__ import annotations

from dataclasses import dataclass, field
from modules.utils import Point, TouchEvent, TouchPhase


@dataclass
class TwoFingerTapTracker:
    """Tracks touch contacts in Menu Mode to detect strict, stationary two-finger taps."""

    max_tap_duration_s: float = 0.25
    max_drift_px: float = 25.0
    sync_window_s: float = 0.12

    _contacts: dict[int, tuple[Point, float]] = field(default_factory=dict)
    _invalidated: bool = False
    _released_contacts: set[int] = field(default_factory=set)

    def reset(self) -> None:
        self._contacts.clear()
        self._released_contacts.clear()
        self._invalidated = False

    def process(self, event: TouchEvent) -> bool:
        cid = event.contact_id
        phase = event.phase
        pos = event.position
        now = event.timestamp

        if phase is TouchPhase.DOWN:
            # If a 3rd finger lands, invalidate immediately
            if len(self._contacts) >= 2:
                self._invalidated = True
                return False

            # Check synchronization window with the first finger
            if len(self._contacts) == 1:
                first_time = next(iter(self._contacts.values()))[1]
                if (now - first_time) > self.sync_window_s:
                    self._invalidated = True
                    return False

            self._contacts[cid] = (pos, now)
            return False

        elif phase is TouchPhase.MOVE:
            if cid in self._contacts:
                origin_pos, _ = self._contacts[cid]
                # If either finger drifts beyond the tap tolerance, cancel
                if (pos - origin_pos).magnitude > self.max_drift_px:
                    self._invalidated = True
            return False

        elif phase is TouchPhase.UP:
            if self._invalidated:
                self._contacts.pop(cid, None)
                if not self._contacts:
                    self.reset()
                return False

            if cid in self._contacts:
                origin_pos, start_time = self._contacts[cid]
                duration = now - start_time
                drift = (pos - origin_pos).magnitude

                # Verify timing and position boundaries
                if duration <= self.max_tap_duration_s and drift <= self.max_drift_px:
                    self._released_contacts.add(cid)
                else:
                    self._invalidated = True

                # Check if both candidate fingers tapped and released cleanly
                if len(self._contacts) == 2 and len(self._released_contacts) == 2:
                    self.reset()
                    return True

                self._contacts.pop(cid, None)
                if not self._contacts:
                    self.reset()
                return False

        return False
