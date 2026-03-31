import csv
import io
from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .models import Estudio, Freezer, Rack, Caja, MuestraBiologica, PosicionTubo, RegistroIngreso

# Agrega esta configuración visual
@admin.register(RegistroIngreso)
class RegistroIngresoAdmin(admin.ModelAdmin):
    # Mostramos tanto el código manual como el del sistema en la tabla
    list_display = ('codigo_lote', 'registro_interno', 'fecha_ingreso')
    search_fields = ('codigo_lote', 'registro_interno')
    # Protegemos el registro interno para que solo sea de lectura visual
    readonly_fields = ('registro_interno', 'fecha_ingreso')
    
# Configuración visual para las Muestras + NUEVA FUNCIÓN DE IMPORTACIÓN
@admin.register(MuestraBiologica)
class MuestraBiologicaAdmin(admin.ModelAdmin):
    list_display = ('bsi_id', 'sample_id', 'material_type', 'study', 'date_entered')
    list_filter = ('study', 'material_type', 'vial_status')
    search_fields = ('bsi_id', 'sample_id')

    # --- INICIO LÓGICA DE IMPORTACIÓN BSI ---
    
    # 1. Le decimos a Django que usaremos un template personalizado para agregar el botón verde
    change_list_template = "admin/inventario/muestrabiologica/change_list.html"

    # 2. Creamos la URL interna para la pantalla de subida
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('importar-csv/', self.admin_site.admin_view(self.importar_csv), name='importar_csv_bsi'),
        ]
        return custom_urls + urls

    # 3. La función que lee el archivo y guarda todo en la base de datos
    def importar_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("archivo_csv")
            
            if not csv_file:
                messages.error(request, "Por favor, selecciona un archivo.")
                return redirect("..")
            
            # Leemos el archivo en memoria (utf-8-sig limpia caracteres ocultos al inicio)
            try:
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                
                # OJO: Como vimos que BSI exporta separado por tabulaciones, usamos \t
                # Si tu Excel lo guardó separado por comas, cambia '\t' por ','
                reader = csv.DictReader(io_string, delimiter='\t') 
                
                muestras_creadas = 0

                # transaction.atomic() asegura que si hay un error, no se guarde el archivo a medias
                with transaction.atomic():
                    for row in reader:
                        bsi_id = row.get('BSI ID', '').strip()
                        if not bsi_id: 
                            continue # Saltamos filas vacías

                        # Extraemos los datos de las columnas
                        sample_id = row.get('Sample ID', '').strip()
                        material = row.get('Material Type', 'Desconocido').strip()
                        status = row.get('Vial Status', 'In').strip()
                        
                        nombre_freezer = row.get('Freezer', '').strip()
                        nombre_rack = row.get('Rack', '').strip()
                        nombre_caja = row.get('Box', '').strip()
                        fila_caja = row.get('Row', '').strip()
                        col_caja = row.get('Col', '').strip()

                        # Si la muestra no tiene ubicación física, no la metemos al mapa
                        if not nombre_freezer or not nombre_rack or not nombre_caja:
                            continue

                        # Jerarquía de equipos (Busca si existe, si no, lo crea)
                        freezer, _ = Freezer.objects.get_or_create(nombre=nombre_freezer)
                        rack, _ = Rack.objects.get_or_create(nombre=nombre_rack, freezer=freezer)
                        caja, _ = Caja.objects.get_or_create(
                            nombre=nombre_caja, rack=rack,
                            defaults={'posicion_fila_en_rack': 1, 'posicion_columna_en_rack': 1, 'filas_de_caja': 10, 'columnas_de_caja': 10}
                        )

                        # Crear la muestra en sí
                        muestra, _ = MuestraBiologica.objects.get_or_create(
                            bsi_id=bsi_id,
                            defaults={'sample_id': sample_id, 'material_type': material, 'vial_status': status}
                        )

                        # Asignarla al hueco exacto de la caja
                        try:
                            posicion = PosicionTubo.objects.get(caja=caja, row=fila_caja, col=col_caja)
                            # Solo la guardamos si el hueco está vacío
                            if not posicion.muestra:
                                posicion.muestra = muestra
                                posicion.save()
                                muestras_creadas += 1
                        except PosicionTubo.DoesNotExist:
                            pass # Ignoramos silenciosamente si la caja física es más chica que la coordenada
                            
                messages.success(request, f"¡Éxito! Se importaron {muestras_creadas} muestras y se ubicaron en el sistema.")
                return redirect("..")

            except Exception as e:
                messages.error(request, f"Error procesando el archivo. Verifica el formato: {str(e)}")
                return redirect("..")

        # Si recién entra a la página (GET), le mostramos el formulario de subida
        context = dict(
            self.admin_site.eachcontext(request),
            title="Importar Inventario desde BSI",
        )
        return render(request, "admin/inventario/importar_csv.html", context)
    # --- FIN LÓGICA DE IMPORTACIÓN BSI ---

# Configuración visual para las Posiciones (¡La más importante!)
@admin.register(PosicionTubo)
class PosicionTuboAdmin(admin.ModelAdmin):
    # Qué columnas mostrar en la tabla
    list_display = ('caja', 'row', 'col', 'obtener_estado')
    # Agregar un panel de filtros a la derecha
    list_filter = ('caja__rack', 'caja') 
    # Barra de búsqueda
    search_fields = ('caja__nombre', 'muestra__bsi_id')

    # Función rápida para mostrar si está ocupado o vacío en la tabla
    def obtener_estado(self, obj):
        if obj.muestra:
            return f"Ocupado por: {obj.muestra.bsi_id}"
        return "Vacío"
    obtener_estado.short_description = "Estado"

# Registramos el resto de manera simple
admin.site.register(Estudio)
admin.site.register(Rack)
admin.site.register(Caja)
admin.site.register(Freezer)