from django.urls import path, include
from . import views

urlpatterns = [
    path('fullname/', views.get_user_fullname),

]