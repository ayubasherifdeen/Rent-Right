from django.urls import path

from apps.negotiations import views

app_name = "negotiations"

urlpatterns = [
    path("tenancy/<uuid:tenancy_id>/", views.negotiation_detail, name="negotiation_detail"),
    path("proposal/<uuid:proposal_id>/counter/", views.counter_proposal_view, name="counter_proposal"),
    path("proposal/<uuid:proposal_id>/accept/", views.accept_proposal_view, name="accept_proposal"),
    path("proposal/<uuid:proposal_id>/reject/", views.reject_proposal_view, name="reject_proposal"),
]
