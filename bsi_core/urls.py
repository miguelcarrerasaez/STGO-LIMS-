from django.contrib import admin
from django.urls import path, include
from inventario import views
from inventario.views import registrar_salida, buscar_muestra, mover_muestra_ajax

urlpatterns = [
    # 1. ADMIN OFUSCADO (¡Cambia 'panel-biobanco' por lo que quieras!)
    path('panel-biobanco/', admin.site.urls),
    
    # --- RUTAS DE SEGURIDAD NATIVAS DE DJANGO ---
    path('cuentas/', include('django.contrib.auth.urls')), 
    
    # --- VISTAS PRINCIPALES ---
    path('', views.dashboard, name='dashboard'),
    path('exportar-csv/', views.exportar_inventario_csv, name='exportar_csv'),
    path('ingresar-muestra/', views.ingresar_muestra, name='ingresar_muestra'),
    path('equipos/', views.mapa_freezers, name='mapa_freezers'),
    path('caja/<int:caja_id>/', views.detalle_caja, name='detalle_caja'),
    path('nuevo-lote/', views.crear_lote, name='crear_lote'),
    path('nueva-caja/', views.crear_caja, name='crear_caja'),
    path('salida-muestra/', registrar_salida, name='registrar_salida'),
    path('buscar/', buscar_muestra, name='buscar_muestra'),
    path('escaner/', views.escaner_movil, name='escaner_movil'),
    path('exportar-reporte/', views.exportar_busqueda_csv, name='exportar_busqueda_csv'),
    # --- RUTAS AJAX / API ---
    path('ajax/cargar-cajas/', views.cargar_cajas, name='ajax_cargar_cajas'),
    path('ajax/cargar-huecos/', views.cargar_huecos, name='ajax_cargar_huecos'),
    path('api/mover-muestra/', mover_muestra_ajax, name='mover_muestra_ajax'),
]