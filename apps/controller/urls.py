from django.urls import path
from . import views

urlpatterns = [
    path('', views.controller_dashboard, name='controller'),
    path('save/', views.save_config, name='save_config'),
]
