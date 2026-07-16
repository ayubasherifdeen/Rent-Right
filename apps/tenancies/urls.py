from django.urls import path

from apps.tenancies import views

app_name = "tenancies"

urlpatterns = [
    # Tenant
    path("", views.my_tenancies, name="my_tenancies"),

    # Landlord
    path("landlord/", views.landlord_tenancies, name="landlord_tenancies"),
    path(
        "create/<uuid:application_pk>/",
        views.create_tenancy_view,
        name="create_tenancy",
    ),
    path(
        "<uuid:pk>/activate/",
        views.activate_tenancy_view,
        name="activate_tenancy",
    ),
    path(
        "<uuid:pk>/special-conditions/",
        views.special_conditions_view,
        name="special_conditions",
    ),

    # Shared
    path("<uuid:pk>/", views.tenancy_detail, name="tenancy_detail"),
    path("<uuid:pk>/agreement/", views.agreement_detail, name="agreement_detail"),
    path(
        "<uuid:pk>/agreement/confirm/",
        views.confirm_agreement_view,
        name="confirm_agreement",
    ),
    
]
