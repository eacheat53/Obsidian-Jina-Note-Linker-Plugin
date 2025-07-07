import functools
import time
import typing as T
from .logger import get_logger

F = T.TypeVar("F", bound=T.Callable[..., T.Any])

def timeit(func: F) -> F:  # type: ignore[misc]
    """Decorator: log execution time of func at DEBUG level."""
    @functools.wraps(func)
    def wrapper(*args: T.Any, **kwargs: T.Any):  # type: ignore[override]
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            get_logger().debug("%s took %.2fs", func.__name__, time.perf_counter() - start)
    return T.cast(F, wrapper)