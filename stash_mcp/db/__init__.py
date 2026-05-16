"""SQL persistence layer (SQLAlchemy 2.x async).

Lazy: importing this package does not open a connection. The engine is
created on first call to :func:`get_engine` and disposed on FastAPI
shutdown via :func:`dispose_engine`.
"""

from .engine import dispose_engine, get_engine
from .models import (
    ApiToken,
    AuditEvent,
    Base,
    Membership,
    Store,
    Tenant,
    User,
)
from .session import get_session, get_sessionmaker

__all__ = [
    "ApiToken",
    "AuditEvent",
    "Base",
    "Membership",
    "Store",
    "Tenant",
    "User",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
