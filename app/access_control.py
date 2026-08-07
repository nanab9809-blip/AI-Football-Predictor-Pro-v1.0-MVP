from __future__ import annotations

from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class Permission(StrEnum):
    VIEW_RESULTS = "view_results"
    VIEW_ANALYTICS = "view_analytics"
    CHANGE_OWN_PASSWORD = "change_own_password"
    RUN_SCANNER = "run_scanner"
    RUN_AUTOMATION = "run_automation"
    RUN_SETTLEMENT = "run_settlement"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_LICENSES = "manage_licenses"
    MANAGE_TRADES = "manage_trades"
    VIEW_SAVED_MATCHES = "view_saved_matches"
    VIEW_LIVE_API_MATCHES = "view_live_api_matches"
    REFRESH_MATCH_ANALYSIS = "refresh_match_analysis"


_MEMBER_PERMISSIONS = {
    Permission.VIEW_RESULTS,
    Permission.VIEW_ANALYTICS,
    Permission.VIEW_SAVED_MATCHES,
    Permission.CHANGE_OWN_PASSWORD,
}
_ADMIN_PERMISSIONS = set(Permission)


class AccessPolicy:
    """One authoritative role/permission policy for UI and backend routes."""

    @staticmethod
    def role_of(user: dict[str, Any] | None) -> Role | None:
        if not user:
            return None
        raw = str(user.get("role") or "MEMBER").upper()
        try:
            return Role(raw)
        except ValueError:
            return Role.MEMBER

    @classmethod
    def permissions_for(cls, user: dict[str, Any] | None) -> set[Permission]:
        role = cls.role_of(user)
        if role in {Role.ADMIN, Role.SUPER_ADMIN}:
            return set(_ADMIN_PERMISSIONS)
        if role == Role.MEMBER:
            return set(_MEMBER_PERMISSIONS)
        return set()

    @classmethod
    def allows(cls, user: dict[str, Any] | None, permission: Permission) -> bool:
        return permission in cls.permissions_for(user)

    @classmethod
    def template_flags(cls, user: dict[str, Any] | None) -> dict[str, bool]:
        permissions = cls.permissions_for(user)
        return {permission.value: permission in permissions for permission in Permission}
