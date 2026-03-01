import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


def is_retriable_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    keywords = [
        "rate limit",
        "429",
        "timeout",
        "temporarily",
        "connection reset",
        "service unavailable",
        "502",
        "503",
        "504",
    ]
    return any(keyword in text for keyword in keywords)


def run_with_retry(
    fn: Callable[[], T],
    max_attempts: int,
    base_delay_seconds: float,
    operation_name: str,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not is_retriable_exception(exc):
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s failed on attempt %d/%d (%s). Retrying in %.2fs.",
                operation_name,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    if last_error:
        raise last_error
    raise RuntimeError(f"{operation_name} failed without exception context.")

