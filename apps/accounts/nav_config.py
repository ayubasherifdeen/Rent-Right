"""
Single source of truth for sidebar nav, per role. Add a nav item here
once and every dashboard variant (landlord/tenant/manager) picks it up
automatically — no per-template edits.

`badge_key` is optional — only set it when a count needs to be computed
per-request (see context_processors.sidebar_nav). Static items omit it.
"""

NAV_CONFIG = {
    "landlord": [
        {"url": "accounts:landlord_dashboard", "label": "Dashboard", "icon": "dashboard"},
        {"url": "listings:create_property", "label": "Add Property", "icon": "add"},
        {"url": "listings:my_listings", "label": "Properties", "icon": "properties"},
        {"url": "applications:received_applications", "label": "Applications", "icon": "applications"},
        {"url": "tenancies:landlord_tenancies", "label": "Tenancies", "icon": "tenancies"},
        {"url": "payments:payments", "label": "Payments", "icon": "payments"},
        {"url": "maintenance:landlord_list", "label": "Maintenance", "icon": "maintenance"},
        
    ],
    "tenant": [
        {"url": "accounts:tenant_dashboard", "label": "Dashboard", "icon": "dashboard"},
        {"url": "listings:property_list", "label": "Find Properties", "icon": "search"},
        {"url": "tenancies:my_tenancies", "label": "My Tenancy", "icon": "tenancies"},
        {"url": "payments:payments", "label": "Payments", "icon": "payments"},
        {"url": "maintenance:tenant_list", "label": "Maintenance", "icon": "maintenance"},
    ],
    "property_manager": [
        {"url": "accounts:manager_dashboard", "label": "Dashboard", "icon": "dashboard"},
        {"url": "accounts:managed_properties", "label": "Managed Properties", "icon": "managed"},
        {"url": "listings:create_property", "label": "Add Property", "icon": "add"},
        {"url": "applications:received_applications", "label": "Applications", "icon": "applications"},
        {"url": "tenancies:landlord_tenancies", "label": "Tenancies", "icon": "tenancies"},
        {"url": "accounts:manager_invites", "label": "Invites", "icon": "invites", "badge_key": "pending_invites_count"},
        {"url": "maintenance:landlord_list", "label": "Maintenance", "icon": "maintenance"},
    ],
}