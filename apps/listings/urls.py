from django.urls import path

from apps import applications as applications_views
from . import views

app_name = 'listings'

urlpatterns = [
    # Public
    path('',                          views.PropertyListView.as_view(),  name='property_list'),
    path('<uuid:pk>/',                views.PropertyDetailView.as_view(), name='property_detail'),
    path('map-data/',                 views.map_data,                     name='map_data'),

    # Landlord / Manager
    path('create/',                   views.create_property,              name='create_property'),
    path('<uuid:pk>/publish/',        views.publish_prompt,               name='publish_prompt'),
    path('my-listings/',              views.my_listings,                 name='my_listings'),
   
]
