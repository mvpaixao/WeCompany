from django.urls import path
from . import views

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('new/', views.new_project, name='new_project'),
    path('<int:pk>/', views.project_thread, name='project_thread'),
    path('<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),
    path('<int:pk>/approve/', views.force_approve, name='force_approve'),
    path('<int:pk>/poll/', views.poll_new_emails, name='poll_emails'),
    path('<int:pk>/activity/', views.poll_activity, name='poll_activity'),
]
