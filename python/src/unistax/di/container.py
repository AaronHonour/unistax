"""Dependency Injection Container implementation.

Provides auto-wiring, lifetime management, and factory registration.
"""

import inspect
import logging
import threading
from collections.abc import Callable
from contextvars import ContextVar
from enum import Enum
from typing import Any, TypeVar, get_type_hints

from .exceptions import CircularDependencyError, DependencyResolutionError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Context variable for scoped instances
_scoped_context: ContextVar[dict[type, Any] | None] = ContextVar("_scoped_context", default=None)


class Lifetime(str, Enum):
    """Service lifetime enumeration."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class ServiceDescriptor:
    """Describes a registered service."""

    def __init__(
        self,
        service_type: type,
        implementation_type: type | None = None,
        factory: Callable[..., Any] | None = None,
        instance: Any | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> None:
        """Initialize ServiceDescriptor.

        Args:
            service_type: Service type
            implementation_type: Implementation type (defaults to service_type)
            factory: Factory function for creating instances
            instance: Pre-created instance for singleton
            lifetime: Service lifetime
        """
        self.service_type = service_type
        self.implementation_type = implementation_type or service_type
        self.factory = factory
        self.instance = instance
        self.lifetime = lifetime


class Container:
    """Dependency Injection Container.

    Supports auto-wiring, multiple lifetimes, and factory registration.

    Examples:
        >>> container = Container()
        >>> container.register(UserService, lifetime=Lifetime.SINGLETON)
        >>> user_service = container.resolve(UserService)

        >>> # Factory registration
        >>> container.register_factory(Logger, lambda: get_logger(__name__))

        >>> # Interface to implementation
        >>> container.register(IUserRepository, SQLUserRepository)
    """

    def __init__(self) -> None:
        """Initialize Container."""
        self._services: dict[type, ServiceDescriptor] = {}
        self._lock = threading.RLock()
        self._resolving: set[type] = set()  # For circular dependency detection

    def register(
        self,
        service_type: type[T],
        implementation_type: type[T] | None = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> "Container":
        """Register a service type.

        Args:
            service_type: The service type (interface)
            implementation_type: The implementation type (defaults to service_type)
            lifetime: Service lifetime

        Returns:
            Self for chaining
        """
        with self._lock:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                implementation_type=implementation_type or service_type,
                lifetime=lifetime,
            )
            self._services[service_type] = descriptor
        return self

    def register_instance(self, service_type: type[T], instance: T) -> "Container":
        """Register a pre-created instance (singleton).

        Args:
            service_type: The service type
            instance: The instance

        Returns:
            Self for chaining
        """
        with self._lock:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                instance=instance,
                lifetime=Lifetime.SINGLETON,
            )
            self._services[service_type] = descriptor
        return self

    def register_factory(
        self,
        service_type: type[T],
        factory: Callable[[], T],
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> "Container":
        """Register a factory function.

        Args:
            service_type: The service type
            factory: Factory function
            lifetime: Service lifetime

        Returns:
            Self for chaining
        """
        with self._lock:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                factory=factory,
                lifetime=lifetime,
            )
            self._services[service_type] = descriptor
        return self

    def resolve(self, service_type: type[T]) -> T:
        """Resolve a service instance.

        Args:
            service_type: The service type to resolve

        Returns:
            Service instance

        Raises:
            DependencyResolutionError: If service cannot be resolved
            CircularDependencyError: If circular dependency detected
        """
        # Check for circular dependencies
        if service_type in self._resolving:
            raise CircularDependencyError(
                f"Circular dependency detected for {service_type.__name__}"
            )

        try:
            self._resolving.add(service_type)
            return self._resolve_internal(service_type)
        finally:
            self._resolving.discard(service_type)

    def _resolve_internal(self, service_type: type[T]) -> T:
        """Internal resolution logic."""
        with self._lock:
            if service_type not in self._services:
                # Try auto-registration
                if self._can_auto_wire(service_type):
                    self.register(service_type, lifetime=Lifetime.TRANSIENT)
                else:
                    raise DependencyResolutionError(
                        f"Service {service_type.__name__} not registered"
                    )

            descriptor = self._services[service_type]

            # Return existing instance for singleton
            if descriptor.lifetime == Lifetime.SINGLETON and descriptor.instance is not None:
                return descriptor.instance  # type: ignore[no-any-return]

            # Check scoped context
            if descriptor.lifetime == Lifetime.SCOPED:
                scoped_instances = _scoped_context.get()
                if scoped_instances is not None and service_type in scoped_instances:
                    return scoped_instances[service_type]  # type: ignore[no-any-return]

            # Create new instance
            instance = self._create_instance(descriptor)

            # Store for singleton
            if descriptor.lifetime == Lifetime.SINGLETON:
                descriptor.instance = instance

            # Store for scoped
            if descriptor.lifetime == Lifetime.SCOPED:
                scoped_instances = _scoped_context.get()
                if scoped_instances is not None:
                    scoped_instances[service_type] = instance
                    _scoped_context.set(scoped_instances)

            return instance  # type: ignore[no-any-return]

    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """Create an instance from descriptor."""
        # Use factory if available
        if descriptor.factory:
            return descriptor.factory()

        # Use constructor
        implementation = descriptor.implementation_type

        try:
            # Get constructor parameters
            sig = inspect.signature(implementation.__init__)  # type: ignore[misc]
            type_hints = get_type_hints(implementation.__init__)  # type: ignore[misc]

            # Build arguments
            kwargs = {}
            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                # Get type hint
                param_type = type_hints.get(param_name)
                if param_type is None:
                    if param.default == inspect.Parameter.empty:
                        raise DependencyResolutionError(
                            f"Cannot resolve {param_name} for {implementation.__name__}: "
                            f"no type hint"
                        )
                    continue

                # Resolve dependency
                kwargs[param_name] = self.resolve(param_type)

            return implementation(**kwargs)

        except Exception as e:
            raise DependencyResolutionError(
                f"Failed to create instance of {implementation.__name__}: {e}"
            ) from e

    def _can_auto_wire(self, service_type: type) -> bool:
        """Check if type can be auto-wired."""
        try:
            # Must be a class
            if not inspect.isclass(service_type):
                return False

            # Must have __init__
            if not hasattr(service_type, "__init__"):
                return False

            # Check if all parameters have type hints
            sig = inspect.signature(service_type.__init__)
            type_hints = get_type_hints(service_type.__init__)

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                if param_name not in type_hints:
                    if param.default == inspect.Parameter.empty:
                        return False

            return True
        except Exception as e:
            logger.debug(
                "Cannot auto-wire type %s: %s",
                service_type.__name__ if hasattr(service_type, "__name__") else service_type,
                e,
            )
            return False

    def create_scope(self) -> "Container":
        """Create a child container for scoped services.

        Returns:
            New scoped container
        """
        child = Container()
        child._services = dict(self._services)  # Share service registrations
        return child

    def clear_scope(self) -> None:
        """Clear scoped instances."""
        _scoped_context.set({})

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Container(services={len(self._services)})"


# Decorator for marking classes as injectable
def injectable(cls: type[T]) -> type[T]:
    """Mark a class as injectable.

    This is optional - the container can auto-wire classes with type hints.
    """
    cls.__injectable__ = True  # type: ignore[attr-defined]
    return cls


# Decorator for injecting dependencies
def inject(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to inject dependencies into a function.

    Example:
        >>> @inject
        ... def process_user(user_service: UserService):
        ...     return user_service.get_all()
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Get container from somewhere (could be passed, or use global)
        # This is a simplified implementation
        container = kwargs.pop("_container", None)
        if container is None:
            return func(*args, **kwargs)

        # Inject dependencies
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        for param_name, param in sig.parameters.items():
            if param_name in kwargs:
                continue

            param_type = type_hints.get(param_name)
            if param_type and param_name not in kwargs:
                try:
                    kwargs[param_name] = container.resolve(param_type)
                except Exception as e:
                    if param.default == inspect.Parameter.empty:
                        raise
                    logger.debug(
                        "Could not resolve dependency %s for parameter %s in function %s: %s",
                        param_type,
                        param_name,
                        func.__name__,
                        e,
                    )

        return func(*args, **kwargs)

    return wrapper
