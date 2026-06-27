"""
applications/urls.py

Namespace: 'applications'

Note: the `apply` URL is NOT here — it's registered in listings/urls.py
so the path stays at /listings/<uuid>/apply/ for URL coherence with the
listing detail page CTA.
"""

from django.urls import path
from . import views

app_name = 'applications'

urlpatterns = [
    path('', views.my_applications, name='my_applications'),
    path('landlord/', views.received_applications, name='received_applications'),
    path('<uuid:pk>/approve/', views.approve_application, name='approve_application'),
    path('<uuid:pk>/decline/', views.decline_application, name='decline_application'),
    path('<uuid:pk>/withdraw/', views.withdraw_application, name='withdraw_application'),
    path('<uuid:pk>/apply/',    views.apply,                        name='apply')

]
