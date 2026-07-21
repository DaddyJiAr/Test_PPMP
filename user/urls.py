from django.urls import path, include
from . import views

urlpatterns = [
    path('header_info/', views.get_header_info),
    path('admin_name/', views.get_admin_name),
    path('update_fullname/', views.update_fullname),
    path('create_user/', views.create_user),
    path('update_user_status/', views.update_user_status),
    path('promote_user/', views.promote_user),
]