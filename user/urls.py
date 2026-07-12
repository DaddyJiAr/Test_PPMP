from django.urls import path, include
from . import views

urlpatterns = [
    path('header_info/', views.get_header_info),

]