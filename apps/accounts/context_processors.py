from .nav_config import NAV_CONFIG
from .services import get_pending_invites_count


def sidebar_nav(request):
    """
    Injects `nav_items` into every template's context, built from the
    logged-in user's role. Unauthenticated requests and roles with no
    config (e.g. admin) just get an empty list — the {% for %} in
    dashboard_base.html renders nothing, no template-side branching
    needed.
    """
    if not request.user.is_authenticated:
        return {}

    role = getattr(request.user, "role", None)
    items = NAV_CONFIG.get(role, [])

    badges = {}
    if role == "property_manager":
        badges["pending_invites_count"] = get_pending_invites_count(request.user)

    nav_items = [
        {**item, "badge": badges.get(item.get("badge_key"))}
        for item in items
    ]
    return {"nav_items": nav_items}