"""Connection pooling optimizations."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class PoolConfig:
    """Connection pool configuration."""

    min_size: int = 5
    max_size: int = 20
    timeout: float = 30.0
    max_idle_time: float = 600.0
    health_check_interval: float = 60.0


class PooledConnection(Generic[T]):
    """Wrapper for pooled connection."""

    def __init__(self, connection: T, pool: "ConnectionPool[T]") -> None:
        """Initialize pooled connection.

        Args:
            connection: Actual connection
            pool: Connection pool
        """
        self.connection = connection
        self.pool = pool
        self.last_used = time.time()

    def __enter__(self) -> T:
        """Enter context manager."""
        return self.connection

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager and return to pool."""
        self.pool.return_connection(self)


class ConnectionPool(Generic[T]):
    """Generic connection pool implementation."""

    def __init__(
        self, connection_factory: Callable[[], T], config: PoolConfig | None = None
    ) -> None:  # noqa: E501
        """Initialize connection pool.

        Args:
            connection_factory: Function to create connections
            config: Pool configuration

        Example:
            def create_conn():
                return database.connect()

            pool = ConnectionPool(create_conn)

            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
        """
        self.connection_factory = connection_factory
        self.config = config or PoolConfig()

        self.pool: Queue[PooledConnection[T]] = Queue(maxsize=self.config.max_size)
        self.size = 0
        self.lock = threading.Lock()

        # Initialize minimum connections
        for _ in range(self.config.min_size):
            self._create_connection()

    def _create_connection(self) -> PooledConnection[T]:
        """Create new connection.

        Returns:
            Pooled connection
        """
        with self.lock:
            if self.size >= self.config.max_size:
                raise RuntimeError("Connection pool exhausted")

            conn = self.connection_factory()
            self.size += 1
            return PooledConnection(conn, self)

    def get_connection(self, timeout: float | None = None) -> PooledConnection[T]:
        """Get connection from pool.

        Args:
            timeout: Timeout in seconds

        Returns:
            Pooled connection

        Raises:
            Empty: If no connection available within timeout
        """
        timeout = timeout or self.config.timeout

        try:
            # Try to get existing connection
            pooled = self.pool.get(timeout=timeout)

            # Check if connection is still healthy
            if time.time() - pooled.last_used > self.config.max_idle_time:
                # Connection too old, create new one
                self._close_connection(pooled)
                return self._create_connection()

            pooled.last_used = time.time()
            return pooled

        except Empty:
            # No available connections, try to create new one
            return self._create_connection()

    def return_connection(self, connection: PooledConnection[T]) -> None:
        """Return connection to pool.

        Args:
            connection: Connection to return
        """
        connection.last_used = time.time()

        try:
            self.pool.put(connection, block=False)
        except Full:
            # Pool full, close connection
            self._close_connection(connection)

    def _close_connection(self, connection: PooledConnection[T]) -> None:
        """Close connection.

        Args:
            connection: Connection to close
        """
        try:
            if hasattr(connection.connection, "close"):
                connection.connection.close()
        except Exception:
            pass
        finally:
            with self.lock:
                self.size -= 1

    def close_all(self) -> None:
        """Close all connections in pool."""
        while not self.pool.empty():
            try:
                conn = self.pool.get(block=False)
                self._close_connection(conn)
            except Empty:
                break

    def stats(self) -> dict[str, Any]:
        """Get pool statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "size": self.size,
            "available": self.pool.qsize(),
            "in_use": self.size - self.pool.qsize(),
            "config": {
                "min_size": self.config.min_size,
                "max_size": self.config.max_size,
            },
        }
