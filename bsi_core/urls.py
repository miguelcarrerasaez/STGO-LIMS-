from django.contrib import admin
from django.urls import path, include  # <-- Agregamos 'include' aquí
from inventario import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- RUTAS DE SEGURIDAD NATIVAS DE DJANGO ---
    path('cuentas/', include('django.contrib.auth.urls')), 
    
    path('', views.dashboard, name='dashboard'),
    path('exportar-csv/', views.exportar_inventario_csv, name='exportar_csv'),
    path('ingresar-muestra/', views.ingresar_muestra, name='ingresar_muestra'),
    path('equipos/', views.mapa_freezers, name='mapa_freezers'),
    path('caja/<int:caja_id>/', views.detalle_caja, name='detalle_caja'),
    path('nuevo-lote/', views.crear_lote, name='crear_lote'),
    path('nueva-caja/', views.crear_caja, name='crear_caja'),
    # --- RUTAS AJAX PARA MENÚS EN CASCADA ---
    path('ajax/cargar-cajas/', views.cargar_cajas, name='ajax_cargar_cajas'),
    path('ajax/cargar-huecos/', views.cargar_huecos, name='ajax_cargar_huecos'),
]