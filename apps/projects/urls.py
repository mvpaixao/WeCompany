from django.urls import path
from . import views

urlpatterns = [
    path('', views.inbox, name='inbox'),
    path('new/', views.new_project, name='new_project'),
    path('<int:pk>/', views.project_thread, name='project_thread'),
    path('<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),
    path('<int:pk>/create-issues/', views.create_issues, name='create_issues'),
    path('<int:pk>/approve/', views.force_approve, name='force_approve'),
    path('<int:pk>/emails/<int:email_pk>/', views.email_detail, name='email_detail'),
    path('<int:pk>/poll/', views.poll_new_emails, name='poll_emails'),
]
