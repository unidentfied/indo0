"""Sindio — Role-Based Access Control (RBAC)
===========================================
Multi-role authorization system for the mock API and ML Core.

Roles:
  - viewer: read-only access to dashboards and reports
  - operator: can run simulations, acknowledge alerts, submit feedback
  - admin: full access including user management, config changes
  - county: read + report access for Nairobi County officials
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

security = HTTPBearer(auto_error=False)

_JWT_SECRET = os.getenv("JWT_SECRET", "")


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    COUNTY = "county"


# Role permissions matrix
_PERMISSIONS: Dict[Role, Dict[str, List[str]]] = {
    Role.VIEWER: {
        "allowed_endpoints": [
            "GET",  # All read endpoints
        ],
        "blocked_patterns": [
            "POST /api/simulate",
            "POST /api/simulations/run",
            "DELETE",
            "PUT /api",
            "PATCH",
        ],
    },
    Role.OPERATOR: {
        "allowed_endpoints": [
            "GET",
            "POST /api/simulate",
            "POST /api/simulations/run",
            "POST /api/v1/feedback",
            "POST /api/v1/acknowledge",
        ],
        "blocked_patterns": [
            "DELETE",
            "PUT /api/users",
            "PUT /api/config",
        ],
    },
    Role.ADMIN: {
        "allowed_endpoints": ["*"],
        "blocked_patterns": [],
    },
    Role.COUNTY: {
        "allowed_endpoints": [
            "GET",
            "POST /api/v1/reports/export",
            "POST /api/v1/feedback",
        ],
        "blocked_patterns": [
            "POST /api/simulate",
            "DELETE",
            "PUT /api",
            "PATCH",
        ],
    },
}


def _extract_role_from_token(token: str) -> Role:
    """Decode JWT and extract role claim."""
    if not _JWT_SECRET:
        raise HTTPException(500, "JWT_SECRET not configured")
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
        role_str = payload.get("role", "viewer")
        return Role(role_str)
    except JWTError as exc:
        raise HTTPException(401, f"Invalid token: {exc}")


def require_role(*allowed_roles: Role):
    """Dependency factory: require specific role(s)."""
    async def _check_role(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> Dict:
        if credentials is None:
            raise HTTPException(401, "Authentication required")

        token = credentials.credentials
        role = _extract_role_from_token(token)

        if role not in allowed_roles:
            raise HTTPException(
                403,
                f"Insufficient permissions. Required: {[r.value for r in allowed_roles]}. Got: {role.value}",
            )

        # Check endpoint-specific permissions
        method = request.method
        path = request.url.path

        perms = _PERMISSIONS.get(role, {})
        blocked = perms.get("blocked_patterns", [])
        for pattern in blocked:
            parts = pattern.split(" ", 1)
            p_method = parts[0]
            p_path = parts[1] if len(parts) > 1 else ""
            if method == p_method or p_method == "*":
                if path.startswith(p_path) or p_path == "*":
                    raise HTTPException(
                        403,
                        f"Role '{role.value}' is not permitted to {method} {path}",
                    )

        return {"role": role, "sub": token}
    return _check_role


# Convenience dependencies
require_viewer = require_role(Role.VIEWER, Role.OPERATOR, Role.ADMIN, Role.COUNTY)
require_operator = require_role(Role.OPERATOR, Role.ADMIN)
require_admin = require_role(Role.ADMIN)
require_county = require_role(Role.COUNTY, Role.ADMIN)
