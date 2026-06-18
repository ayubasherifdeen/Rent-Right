"""
config/urls.py — root URL dispatcher.

Pattern: each app owns its own urls.py with a namespace.
Add app URL includes here as we build each module.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView


urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Redirect bare root to login
    path('', RedirectView.as_view(url='/accounts/login/', permanent=False)),

    # Apps
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),
    path('listings/',     include('apps.listings.urls',     namespace='listings')),
    # path('applications/', include('apps.applications.urls', namespace='applications')),
    # path('tenancies/',    include('apps.tenancies.urls',    namespace='tenancies')),
    # path('negotiations/', include('apps.negotiations.urls', namespace='negotiations')),
    # path('payments/',     include('apps.payments.urls',     namespace='payments')),
    # path('documents/',    include('apps.documents.urls',    namespace='documents')),
    # path('maintenance/',  include('apps.maintenance.urls',  namespace='maintenance')),
    # path('analytics/',    include('apps.analytics.urls',    namespace='analytics')),
]

# Serve media files in development only
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

