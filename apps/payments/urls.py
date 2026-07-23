from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("<uuid:pk>/pay/move-in/", views.initiate_move_in_payment_view, name="pay_move_in"),
    path(
        "<uuid:pk>/pay/instalment/<str:due_date>/",
        views.initiate_instalment_payment_view,
        name="pay_instalment",
    ),
    path("callback/", views.payment_callback_view, name="payment_callback"),
    path("webhook/", views.paystack_webhook_view, name="paystack_webhook"),
    path("<uuid:pk>/history/", views.payment_history_view, name="payment_history"),
]
