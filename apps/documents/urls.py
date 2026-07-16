from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("<uuid:document_id>/download/", views.download_document, name="download"),
]
