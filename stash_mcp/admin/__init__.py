"""Admin HTTP surface — tenants, stores, users, memberships.

All endpoints under :data:`router` require the in-flight principal to
have ``admin`` role on the default tenant (see
:func:`require_admin`). Errors render as RFC 7807 Problem Details.
"""

from .routes import router

__all__ = ["router"]
