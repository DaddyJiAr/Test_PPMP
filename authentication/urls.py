from django.urls import path, include
from . import views

urlpatterns = [
    # path('', views.get_users),
    # path('test/', views.get_user_test),
    path('login/', views.login),
    path('logout/', views.get_users),
    path('signup/', views.get_users),
    # path('role/', views.get_role),
]