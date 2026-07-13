from django.urls import path, include
from . import views

urlpatterns = [
    path('auth/', include('authentication.urls')),
    path('user/', include('user.urls')),
    path('preview/', views.get_ppmp_preview),
    path('import/', views.upload),
    path('masterlist/', views.masterlist),
    path('masterlist_cards/', views.masterlist_cards),
    path('fiscal_years/', views.fiscal_years),
    path('dashboard_cards/', views.dashboard_cards),
    path('purchase_request/', views.purchase_request),

]