from django.urls import path
from . import views

urlpatterns = [
    path('sync/', views.UsageSyncView.as_view(), name='usage-sync'),
    path('activity/', views.ActivityView.as_view(), name='activity'),
    path('report/', views.ReportView.as_view(), name='report'),
]
