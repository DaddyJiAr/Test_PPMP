from django.urls import path, include
from . import views

urlpatterns = [
    path('header_info/', views.get_header_info),
    path('admin_name/', views.get_admin_name),
    path('signatories/', views.get_signatories),
    path('update_fullname/', views.update_fullname),
]