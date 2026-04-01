import csv
import io
from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from datetime import datetime
from .models import Estudio, Freezer, Rack, Caja, MuestraBiologica, PosicionTubo, RegistroIngreso, TipoMaterial, TipoVial

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
# Asegúrate de agregar esta importación arriba de todo en tu admin.py:
# from datetime import datetime

    # 3. La función que lee el archivo y guarda todo en la base de datos
    def importar_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("archivo_csv")
            
            if not csv_file:
                messages.error(request, "Por favor, selecciona un archivo.")
                return redirect("..")
            
            try:
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                
                # AUTO-DETECCIÓN: ¿Es un CSV (comas) o un TXT de BSI (tabulaciones)?
                dialect = csv.Sniffer().sniff(io_string.read(1024))
                io_string.seek(0)
                reader = csv.DictReader(io_string, dialect=dialect) 
                
                muestras_creadas = 0
                muestras_actualizadas = 0
                errores_ubicacion = []

                # transaction.atomic() asegura que si hay un error crítico, se deshace todo
                with transaction.atomic():
                    
                    # 1. CREAMOS EL LOTE DE MIGRACIÓN AUTOMÁTICO
                    fecha_str = datetime.now().strftime('%Y%m%d-%H%M')
                    lote_migracion = RegistroIngreso.objects.create(
                        codigo_lote=f"MIGRACION-BSI-{fecha_str}"
                    )

                    for row in reader:
                        bsi_id = row.get('BSI ID', '').strip()
                        if not bsi_id: 
                            continue # Saltamos filas vacías

                        # --- PARSEO DE DATOS NUMÉRICOS Y BOOLEANOS ---
                        volumen_str = row.get('Volume', '').strip()
                        volumen = float(volumen_str) if volumen_str else None

                        thaws_str = row.get('Thaws', '').strip()
                        thaws = int(thaws_str) if thaws_str else 0

                        # BSI a veces guarda 'Y' o 'Yes' para hemolizado
                        hemolizada = str(row.get('Hemolyzed', '')).strip().upper() in ['Y', 'YES', 'TRUE', '1']

                        # --- PARSEO DE FECHAS (Limpiamos el .0 de los milisegundos de BSI) ---
                        def parse_bsi_date(date_str):
                            if not date_str: return None
                            try:
                                clean_date = date_str.split('.')[0] # Quita el ".0" final
                                return datetime.strptime(clean_date, '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                return None

                        # --- PARSEO DE TABLAS MAESTRAS ---
                        material_str = row.get('Material Type', '').strip()
                        vial_str = row.get('Vial Type', '').strip()
                        
                        tipo_mat_obj = None
                        if material_str:
                            tipo_mat_obj, _ = TipoMaterial.objects.get_or_create(nombre=material_str)
                            
                        tipo_vial_obj = None
                        if vial_str:
                            tipo_vial_obj, _ = TipoVial.objects.get_or_create(nombre=vial_str)

                        # 2. CREAMOS O ACTUALIZAMOS LA MUESTRA
                        muestra, created = MuestraBiologica.objects.update_or_create(
                            bsi_id=bsi_id,
                            defaults={
                                'sample_id': row.get('Sample ID', '').strip(),
                                'project': row.get('Project', '').strip(),
                                'subject_id': row.get('Subject ID', '').strip(),
                                'parent_id': row.get('Parent ID', '').strip(),
                                
                                # AQUÍ USAMOS LOS NUEVOS OBJETOS DE LAS TABLAS MAESTRAS
                                'material_type': tipo_mat_obj,
                                'vial_type': tipo_vial_obj,
                                
                                'vial_status': row.get('Vial Status', 'Disponible').strip(),
                                'volume': volumen,
                                'volume_unit': row.get('Volume Unit', '').strip(),
                                'thaws': thaws,
                                'hemolyzed': hemolizada,
                                'vial_warnings': row.get('Vial Warnings', '').strip(),
                                'date_drawn': parse_bsi_date(row.get('Date Drawn', '')),
                                'date_received': parse_bsi_date(row.get('Date Received', '')),
                                'date_frozen': parse_bsi_date(row.get('Date Frozen', '')),
                                'entry_batch': lote_migracion, 
                            }
                        )

                        if created: muestras_creadas += 1
                        else: muestras_actualizadas += 1

                        # 3. LÓGICA DE UBICACIÓN FÍSICA
                        nombre_freezer = row.get('Freezer', '').strip()
                        nombre_rack = row.get('Rack', '').strip()
                        nombre_caja = row.get('Box', '').strip()
                        
                        bsi_row = row.get('Row', '').strip()
                        bsi_col = row.get('Col', '').strip()

                        if nombre_freezer and nombre_rack and nombre_caja and bsi_row and bsi_col:
                            
                            # --- EL DETECTOR INTELIGENTE ---
                            # BSI cruza las coordenadas. Nuestro LIMS exige: 'row' = Letra, 'col' = Número
                            fila_lims = ""
                            col_lims = 0
                            
                            try:
                                if bsi_row.isdigit():
                                    col_lims = int(bsi_row)
                                    fila_lims = bsi_col.upper()
                                else:
                                    col_lims = int(bsi_col) if bsi_col.isdigit() else 0
                                    fila_lims = bsi_row.upper()
                            except ValueError:
                                errores_ubicacion.append(f"{bsi_id} (Coordenadas corruptas en CSV)")
                                continue

                            freezer, _ = Freezer.objects.get_or_create(nombre=nombre_freezer)
                            rack, _ = Rack.objects.get_or_create(nombre=nombre_rack, freezer=freezer, defaults={'filas_alto': 5, 'columnas_ancho': 5})
                            caja, _ = Caja.objects.get_or_create(
                                nombre=nombre_caja, rack=rack,
                                defaults={
                                    'posicion_fila_en_rack': 1, 'posicion_columna_en_rack': 1, 
                                    'filas_de_caja': 10, 'columnas_de_caja': 10 
                                }
                            )

                            try:
                                # Buscamos el hueco usando la variable correcta para cada eje
                                posicion = PosicionTubo.objects.get(caja=caja, row=fila_lims, col=col_lims)
                                muestra.ubicacion = posicion
                                muestra.save()
                            except PosicionTubo.DoesNotExist:
                                errores_ubicacion.append(f"{bsi_id} (Posición {fila_lims}{col_lims} no existe en caja de 10x10)")
                            
                # 4. REPORTAMOS RESULTADOS AL USUARIO
                mensaje_final = f"¡Éxito! {muestras_creadas} nuevas y {muestras_actualizadas} actualizadas. Asignadas al lote {lote_migracion.codigo_lote}."
                
                if errores_ubicacion:
                    mensaje_final += f" ADVERTENCIA: {len(errores_ubicacion)} muestras no se pudieron ubicar en el mapa físico por coordenadas inválidas."
                    messages.warning(request, mensaje_final)
                else:
                    messages.success(request, mensaje_final)
                    
                return redirect("..")

            except Exception as e:
                messages.error(request, f"Error crítico procesando el archivo: {str(e)}")
                return redirect("..")
        context = dict(
            self.admin_site.each_context(request),
            title="Importar Inventario desde BSI",
        )
        return render(request, "admin/inventario/importar_csv.html", context)    

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
admin.site.register(TipoMaterial)
admin.site.register(TipoVial)