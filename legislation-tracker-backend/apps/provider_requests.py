"""Common retry decisions for upstream reads and paid generation requests."""

import signal
import threading
from contextlib import contextmanager
from enum import Enum


class FailureKind(Enum):
    COOLDOWN = "cooldown"
    RETRYABLE = "retryable"
    INVALID_OUTPUT = "invalid_output"
    AMBIGUOUS = "ambiguous"
    TERMINAL = "terminal"


def classify_failure(error):
    if getattr(error, "outcome_unknown", False):
        return FailureKind.AMBIGUOUS
    category = getattr(error, "category", None)
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429 or category == "provider_rate_limited":
        return FailureKind.COOLDOWN
    if category == "invalid_output":
        return FailureKind.INVALID_OUTPUT
    if (
        getattr(error, "retry_allowed", False)
        or category == "provider_unavailable"
        or (isinstance(status, int) and status >= 500)
    ):
        return FailureKind.RETRYABLE
    return FailureKind.TERMINAL


@contextmanager
def total_request_deadline(seconds, *, error_factory):
    """Interrupt a stalled HTTP read instead of waiting for another chunk.

    ``requests`` applies its read timeout to individual socket reads.  A peer
    that slowly drips bytes can therefore keep an ``iter_content`` call open
    forever without triggering that timeout.  Celery executes this client in
    its worker main thread on POSIX, where an interval timer can interrupt the
    blocked system call at the request-wide deadline.

    Do not replace an active timer owned by the host process. The previous
    alarm handler is restored after every request, so Celery's idle handler can
    coexist with this deadline. The ordinary requests timeout and
    between-chunk check remain the portable fallback for non-POSIX platforms.
    """
    can_interrupt = (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "ITIMER_REAL")
        and hasattr(signal, "getitimer")
        and hasattr(signal, "setitimer")
    )
    if not can_interrupt:
        yield False
        return

    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    previous_handler = signal.getsignal(signal.SIGALRM)
    if remaining or interval:
        yield False
        return

    def _raise_total_timeout(_signum, _frame):
        raise error_factory()

    signal.signal(signal.SIGALRM, _raise_total_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
