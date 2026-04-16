import csv
import io
from django.contrib import admin
from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
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

    def importar_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("archivo_csv")
            
            if not csv_file:
                messages.error(request, "Por favor, selecciona un archivo.")
                return redirect("..")
            
            try:
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                
                dialect = csv.Sniffer().sniff(io_string.read(1024))
                io_string.seek(0)
                reader = csv.DictReader(io_string, dialect=dialect) 
                
                errores_ubicacion = []

                with transaction.atomic():
                    # 1. CREAMOS EL LOTE DE MIGRACIÓN AUTOMÁTICO
                    fecha_str = timezone.now().strftime('%Y%m%d-%H%M')
                    lote_migracion = RegistroIngreso.objects.create(
                        codigo_lote=f"MIGRACION-BSI-{fecha_str}"
                    )

                    # =========================================================
                    # FASE DE CACHÉ EN MEMORIA (El secreto de la velocidad)
                    # =========================================================
                    materiales_cache = {m.nombre: m for m in TipoMaterial.objects.all()}
                    viales_cache = {v.nombre: v for v in TipoVial.objects.all()}
                    freezer_cache = {f.nombre: f for f in Freezer.objects.all()}
                    rack_cache = {f"{r.freezer_id}-{r.nombre}": r for r in Rack.objects.all()}
                    caja_cache = {f"{c.rack_id}-{c.nombre}": c for c in Caja.objects.all()}
                    posiciones_cache = {f"{p.caja_id}-{p.row}-{p.col}": p for p in PosicionTubo.objects.all()}
                    
                    muestras_existentes = {m.bsi_id: m for m in MuestraBiologica.objects.all()}

                    # Listas donde guardaremos los datos antes del gran viaje a la DB
                    muestras_a_crear = []
                    muestras_a_actualizar = []
                    campos_a_actualizar = [
                        'sample_id', 'project', 'subject_id', 'parent_id', 'material_type', 
                        'vial_type', 'vial_status', 'volume', 'volume_unit', 'thaws', 
                        'hemolyzed', 'vial_warnings', 'date_drawn', 'date_received', 
                        'date_frozen', 'entry_batch', 'ubicacion'
                    ]

                    for row in reader:
                        bsi_id = row.get('BSI ID', '').strip()
                        if not bsi_id: 
                            continue

                        # --- PARSEO BÁSICO ---
                        volumen_str = row.get('Volume', '').strip()
                        volumen = float(volumen_str) if volumen_str else None
                        thaws_str = row.get('Thaws', '').strip()
                        thaws = int(thaws_str) if thaws_str else 0
                        hemolizada = str(row.get('Hemolyzed', '')).strip().upper() in ['Y', 'YES', 'TRUE', '1']

                        def parse_bsi_date(date_str):
                            if not date_str: return None
                            try:
                                clean_date = date_str.split('.')[0]
                                fecha_ingenua = datetime.strptime(clean_date, '%Y-%m-%d %H:%M:%S')
                                # Arreglamos la advertencia de zona horaria de Django
                                return timezone.make_aware(fecha_ingenua)
                            except ValueError:
                                return None

                        # --- LÓGICA DE TABLAS MAESTRAS (Usando la RAM, no la DB) ---
                        material_str = row.get('Material Type', '').strip()
                        if material_str and material_str not in materiales_cache:
                            materiales_cache[material_str] = TipoMaterial.objects.create(nombre=material_str)
                        tipo_mat_obj = materiales_cache.get(material_str)

                        vial_str = row.get('Vial Type', '').strip()
                        if vial_str and vial_str not in viales_cache:
                            viales_cache[vial_str] = TipoVial.objects.create(nombre=vial_str)
                        tipo_vial_obj = viales_cache.get(vial_str)

                        # --- LÓGICA DE UBICACIÓN (Usando la RAM, no la DB) ---
                        nombre_freezer = row.get('Freezer', '').strip()
                        nombre_rack = row.get('Rack', '').strip()
                        nombre_caja = row.get('Box', '').strip()
                        bsi_row = row.get('Row', '').strip()
                        bsi_col = row.get('Col', '').strip()
                        
                        ubicacion_final = None

                        if nombre_freezer and nombre_rack and nombre_caja and bsi_row and bsi_col:
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

                            # Navegación rápida por diccionarios en RAM
                            if nombre_freezer not in freezer_cache:
                                freezer_cache[nombre_freezer] = Freezer.objects.create(nombre=nombre_freezer)
                            freezer = freezer_cache[nombre_freezer]

                            rack_key = f"{freezer.id}-{nombre_rack}"
                            if rack_key not in rack_cache:
                                rack_cache[rack_key] = Rack.objects.create(nombre=nombre_rack, freezer=freezer, filas_alto=5, columnas_ancho=5)
                            rack = rack_cache[rack_key]

                            caja_key = f"{rack.id}-{nombre_caja}"
                            if caja_key not in caja_cache:
                                nueva_caja = Caja.objects.create(
                                    nombre=nombre_caja, rack=rack,
                                    posicion_fila_en_rack=1, posicion_columna_en_rack=1, 
                                    filas_de_caja=10, columnas_de_caja=10 
                                )
                                caja_cache[caja_key] = nueva_caja
                                
                                # --- EL PARCHE ---
                                # Actualizamos la memoria RAM con los 100 huecos de esta nueva caja
                                nuevas_posiciones = PosicionTubo.objects.filter(caja=nueva_caja)
                                for p in nuevas_posiciones:
                                    pos_key_nuevo = f"{nueva_caja.id}-{p.row}-{p.col}"
                                    posiciones_cache[pos_key_nuevo] = p

                            caja = caja_cache[caja_key]

                            pos_key = f"{caja.id}-{fila_lims}-{col_lims}"
                            if pos_key in posiciones_cache:
                                ubicacion_final = posiciones_cache[pos_key]
                            else:
                                errores_ubicacion.append(f"{bsi_id} (Posición {fila_lims}{col_lims} no existe en la caja)")

                        # =========================================================
                        # EMPAQUETADO DE MUESTRAS (Aún no guardamos nada)
                        # =========================================================
                        if bsi_id in muestras_existentes:
                            m_obj = muestras_existentes[bsi_id]
                            m_obj.sample_id = row.get('Sample ID', '').strip()
                            m_obj.project = row.get('Project', '').strip()
                            m_obj.subject_id = row.get('Subject ID', '').strip()
                            m_obj.parent_id = row.get('Parent ID', '').strip()
                            m_obj.material_type = tipo_mat_obj
                            m_obj.vial_type = tipo_vial_obj
                            m_obj.vial_status = row.get('Vial Status', 'Disponible').strip()
                            m_obj.volume = volumen
                            m_obj.volume_unit = row.get('Volume Unit', '').strip()
                            m_obj.thaws = thaws
                            m_obj.hemolyzed = hemolizada
                            m_obj.vial_warnings = row.get('Vial Warnings', '').strip()
                            m_obj.date_drawn = parse_bsi_date(row.get('Date Drawn', ''))
                            m_obj.date_received = parse_bsi_date(row.get('Date Received', ''))
                            m_obj.date_frozen = parse_bsi_date(row.get('Date Frozen', ''))
                            m_obj.entry_batch = lote_migracion
                            m_obj.ubicacion = ubicacion_final
                            
                            muestras_a_actualizar.append(m_obj)
                        else:
                            nueva_muestra = MuestraBiologica(
                                bsi_id=bsi_id,
                                sample_id=row.get('Sample ID', '').strip(),
                                project=row.get('Project', '').strip(),
                                subject_id=row.get('Subject ID', '').strip(),
                                parent_id=row.get('Parent ID', '').strip(),
                                material_type=tipo_mat_obj,
                                vial_type=tipo_vial_obj,
                                vial_status=row.get('Vial Status', 'Disponible').strip(),
                                volume=volumen,
                                volume_unit=row.get('Volume Unit', '').strip(),
                                thaws=thaws,
                                hemolyzed=hemolizada,
                                vial_warnings=row.get('Vial Warnings', '').strip(),
                                date_drawn=parse_bsi_date(row.get('Date Drawn', '')),
                                date_received=parse_bsi_date(row.get('Date Received', '')),
                                date_frozen=parse_bsi_date(row.get('Date Frozen', '')),
                                entry_batch=lote_migracion,
                                ubicacion=ubicacion_final
                            )
                            muestras_a_crear.append(nueva_muestra)

                    # =========================================================
                    # EL IMPACTO MASIVO A LA BASE DE DATOS (1 Solo Viaje)
                    # =========================================================
                    if muestras_a_crear:
                        MuestraBiologica.objects.bulk_create(muestras_a_crear, batch_size=500)
                    if muestras_a_actualizar:
                        MuestraBiologica.objects.bulk_update(muestras_a_actualizar, campos_a_actualizar, batch_size=500)

                # 4. REPORTAMOS RESULTADOS AL USUARIO
                mensaje_final = f"¡Migración Turbo Exitosa! {len(muestras_a_crear)} nuevas y {len(muestras_a_actualizar)} actualizadas. Lote: {lote_migracion.codigo_lote}."
                
                if errores_ubicacion:
                    mensaje_final += f" ADVERTENCIA: {len(errores_ubicacion)} muestras tienen coordenadas inválidas o cajas faltantes."
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