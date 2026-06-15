from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Auth
    path('register/',            views.register,                 name='register'),
    path('login/',               views.user_login,               name='login'),
    path('logout/',              views.user_logout,              name='logout'),

    # Phone verification
    path('verify-phone/',        views.verify_phone,             name='verify_phone'),
    path('verify-phone/resend/', views.resend_verification_otp,  name='resend_verification_otp'),

    # Dashboards
    path('dashboard/',           views.dashboard,                name='dashboard'),
    path('dashboard/landlord/',  views.landlord_dashboard,       name='landlord_dashboard'),
    path('dashboard/tenant/',    views.tenant_dashboard,         name='tenant_dashboard'),
    path('dashboard/manager/',   views.manager_dashboard,        name='manager_dashboard'),
    path('dashboard/admin/',     views.admin_dashboard,          name='admin_dashboard'),

    # Profile
    path('profile/',             views.profile,                  name='profile'),

    # Password reset
    path('password-reset/',          views.password_reset_request, name='password_reset_request'),
    path('password-reset/confirm/',  views.password_reset_confirm, name='password_reset_confirm'),
]

