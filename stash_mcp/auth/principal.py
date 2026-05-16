"""Principal value object — the authenticated identity attached to a request."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

AuthMethod = Literal["session", "oidc", "api_token"]
Role = Literal["admin", "member"]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    oidc_sub: str
    email: str
    display_name: str
    auth_method: AuthMethod
    tenant_roles: dict[UUID, Role] = field(default_factory=dict)
    claims: dict[str, object] = field(default_factory=dict)

    def has_role_on(self, tenant_id: UUID, role: Role) -> bool:
        current = self.tenant_roles.get(tenant_id)
        if current is None:
            return False
        if role == "member":
            return current in ("admin", "member")
        return current == role
