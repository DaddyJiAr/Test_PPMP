from django.urls import path, include
from . import views

urlpatterns = [
    path('auth/', include('authentication.urls')),
    path('user/', include('user.urls')),
    path('preview/', views.get_ppmp_preview),
    path('import/', views.upload),
    path('export/', views.export),
    path('fiscal_years/', views.fiscal_years),
    path('dashboard_cards/', views.dashboard_cards),
    path('masterlist/', views.masterlist_data),
    path('masterlist_cards/', views.masterlist_cards),
    path('purchase_request/', views.purchase_request),
    path('procurement_monitoring/', views.procurement_data),
    path('procurement_status/', views.update_purchase_request_status),
    path('in_lieu_data/', views.get_in_lieu_data),
    path('create_in_lieu/', views.create_in_lieu_request),
    path('in_lieu_approvals/', views.get_in_lieu_approvals),
    path('in_lieu_approval_status/', views.update_in_lieu_status),
    path('signatories/', views.get_signatories),
]