"""CancellationToken - cooperative cancellation for async runtime loops.

Thread-safe token that supports:
- cancel() to signal cancellation
- on_cancel(callback) to register cleanup callbacks
- is_cancelled property to check state
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class CancellationToken:
    """Cooperative cancellation token for agent runtime loops.

    Thread-safe: cancel() and on_cancel() can be called from any thread.
    Callbacks registered after cancel() are invoked immediately.
    """

    _cancelled: bool = field(default=False, init=False)
    _callbacks: list[Callable[[], None]] = field(default_factory=list, init=False)
    _lock: Lock = field(default_factory=Lock, repr=False, init=False)

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled

    def cancel(self) -> None:
        """Signal cancellation and invoke all registered callbacks.

        Idempotent: calling cancel() multiple times is safe.
        Callbacks are invoked only on the first cancel() call.
        """
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb()
            except Exception:
                logger.warning("Cancellation callback error", exc_info=True)

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a callback to be invoked on cancellation.

        If already cancelled, the callback is invoked immediately.
        """
        with self._lock:
            if self._cancelled:
                invoke_now = True
            else:
                self._callbacks.append(callback)
                invoke_now = False

        if invoke_now:
            try:
                callback()
            except Exception:
                logger.warning("Cancellation callback error", exc_info=True)
