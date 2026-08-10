from django.urls import path

from . import views

app_name = "maintenance"

urlpatterns = [
    path("tenancy/<uuid:tenancy_pk>/report/", views.report_maintenance, name="report"),
    path("mine/", views.tenant_maintenance_list, name="tenant_list"),
    path("landlord/", views.landlord_maintenance_list, name="landlord_list"),
    path("<uuid:pk>/", views.maintenance_detail, name="detail"),
    path("<uuid:pk>/acknowledge/", views.acknowledge_maintenance, name="acknowledge"),
    path("<uuid:pk>/resolve/", views.resolve_maintenance, name="resolve"),
    path("<uuid:pk>/cancel/", views.cancel_maintenance, name="cancel"),
]
