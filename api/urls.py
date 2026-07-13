from django.urls import path, include
from . import views

urlpatterns = [
    path('auth/', include('authentication.urls')),
    path('user/', include('user.urls')),
    path('preview/', views.get_ppmp_preview),
    path('import/', views.upload),
    path('fiscal_years/', views.fiscal_years),
    path('dashboard_cards/', views.dashboard_cards),
    path('masterlist/', views.masterlist_data),
    path('masterlist_cards/', views.masterlist_cards),
    path('purchase_request/', views.purchase_request),
    path('procurement_monitoring/', views.procurement_data),

]