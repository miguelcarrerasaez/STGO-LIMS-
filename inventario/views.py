from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required # 1. Importamos el "guardia de seguridad"
from django.contrib.admin.views.decorators import staff_member_required
import csv
from django.db.models import Q
from .models import MuestraBiologica, TipoMaterial, Estudio, Rack, Caja, RegistroIngreso, Freezer, PosicionTubo, MovimientoMuestra
from .forms import MuestraBiologicaForm, RegistroIngresoForm, CajaForm, SalidaMuestraForm, ExportarCSVForm
from django.contrib import messages
import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import MovimientoMuestra # Para guardar el historial


# 2. Le ponemos el guardia a nuestra vista. 
# Si no está logueado, lo mandamos a la pantalla de login del admin por ahora.
@login_required
def ingresar_muestra(request):
    # Si el usuario hizo clic en "Guardar" (envió datos por POST)
    if request.method == 'POST':
        form = MuestraBiologicaForm(request.POST)
        if form.is_valid():
            form.save() # Guarda la muestra en la base de datos
            return redirect('dashboard') # Lo devuelve al panel principal
    else:
        # Si recién entró a la página, le mostramos el formulario en blanco
        form = MuestraBiologicaForm()

    return render(request, 'inventario/ingreso_muestra.html', {'form': form})

@login_required
def dashboard(request):
    # Tus conteos actuales
    total_muestras = MuestraBiologica.objects.count()
    total_racks = Rack.objects.count()
    total_cajas = Caja.objects.count()
    ultimos_ingresos = RegistroIngreso.objects.all().order_by('-fecha_ingreso')[:5]
    
    # NUEVO: Traemos todos los freezers
    freezers = Freezer.objects.all()

    return render(request, 'inventario/dashboard.html', {
        'total_muestras': total_muestras,
        'total_racks': total_racks,
        'total_cajas': total_cajas,
        'ultimos_ingresos': ultimos_ingresos,
        'freezers': freezers, # <-- No olvides agregar esto al contexto
    })

@staff_member_required
def exportar_inventario_csv(request):
    if request.method == 'POST':
        form = ExportarCSVForm(request.POST)
        if form.is_valid():
            columnas_seleccionadas = form.cleaned_data['columnas']
            
            # 1. Configurar la respuesta como un archivo descargable
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="reporte_personalizado_lims.csv"'
            
            # TRUCO PRO: Agregar BOM de UTF-8 para que Excel lea los tildes automáticamente
            response.write('\ufeff'.encode('utf8'))
            
            # Usar punto y coma suele ser mejor para Excel en Latinoamérica/España
            writer = csv.writer(response, delimiter=';') 
            
            # 2. Escribir la fila de Encabezados (traduciendo el nombre técnico al nombre legible)
            nombres_legibles = dict(form.fields['columnas'].choices)
            encabezados = [nombres_legibles[col] for col in columnas_seleccionadas]
            writer.writerow(encabezados)
            
            # 3. Traer los datos optimizados de la BD
            muestras = MuestraBiologica.objects.all().select_related(
                'entry_batch', 
                'ubicacion__caja__rack__freezer'
            )
            # --- LA MAGIA DE LOS FILTROS ---
            # Leemos qué seleccionó el usuario en los desplegables
            freezer_filtro = form.cleaned_data.get('freezer')
            rack_filtro = form.cleaned_data.get('rack')
            caja_filtro = form.cleaned_data.get('caja')

            # Filtramos de lo más específico a lo más general.
            # Si eligió una caja, filtramos por esa caja.
            if caja_filtro:
                muestras = muestras.filter(ubicacion__caja=caja_filtro)
            # Si no eligió caja pero sí un rack, filtramos por todo el rack.
            elif rack_filtro:
                muestras = muestras.filter(ubicacion__caja__rack=rack_filtro)
            # Si solo eligió el Freezer (ej: UFMAU05), filtramos por todo el freezer.
            elif freezer_filtro:
                muestras = muestras.filter(ubicacion__caja__rack__freezer=freezer_filtro)
                
            # 4. Escribir las filas de datos dinámicamente
            for muestra in muestras:
                fila = []
                for col in columnas_seleccionadas:
                    # Casos especiales que no son campos directos de texto:
                    if col == 'ubicacion_fisica':
                        if muestra.ubicacion:
                            u = muestra.ubicacion
                            val = f"{u.caja.rack.freezer.nombre} > {u.caja.rack.nombre} > {u.caja.nombre} > {u.row}{u.col}"
                        else:
                            val = "Sin ubicación física"
                    
                    elif col == 'entry_batch':
                        val = muestra.entry_batch.codigo_lote if muestra.entry_batch else "Sin Lote"
                    
                    elif col == 'hemolyzed':
                        val = "Sí" if muestra.hemolyzed else "No"
                        
                    elif col in ['date_drawn', 'date_received']:
                        fecha = getattr(muestra, col)
                        val = fecha.strftime("%Y-%m-%d %H:%M") if fecha else ""
                        
                    # Caso general (textos, números)
                    else:
                        val = getattr(muestra, col, "")
                        if val is None: val = ""
                        
                    fila.append(val)
                    
                writer.writerow(fila)
                
            return response
    else:
        # Si entra por primera vez, le mostramos el formulario
        form = ExportarCSVForm()

    # Reutilizamos tu plantilla de formularios
    return render(request, 'inventario/formulario_base.html', {
        'form': form, 
        'titulo': '📊 Exportar Reporte Personalizado'
    })

@login_required
def mapa_freezers(request):
    # Traemos los freezers, pre-cargamos los racks, y DENTRO de los racks, pre-cargamos las cajas.
    freezers = Freezer.objects.prefetch_related('racks__cajas').all()
    return render(request, 'inventario/mapa_freezers.html', {'freezers': freezers})

@login_required
def detalle_caja(request, caja_id):
    caja = get_object_or_404(Caja, id=caja_id)
    
    # Buscamos todas las posiciones de esta caja
    posiciones = caja.posiciones.all().select_related('muestra')
    
    # 1. EL ESCUDO PROTECTOR: Armamos el diccionario preguntando con cuidado
    tubos_dict = {}
    for pos in posiciones:
        # Preguntamos si el hueco tiene muestra antes de sacarla
        tubos_dict[f"{pos.row}{pos.col}"] = pos.muestra if hasattr(pos, 'muestra') else None

    # Generamos la cuadrícula usando tu mismo sistema de letras
    cuadricula = []
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    
    # 2. ACTUALIZACIÓN DE NOMBRES: Usamos tus nuevas variables
    for f in range(caja.filas_de_caja):
        fila_actual = []
        letra_fila = letras[f] if f < len(letras) else str(f)
        
        for c in range(1, caja.columnas_de_caja + 1):
            coordenada = f"{letra_fila}{c}"
            muestra_aqui = tubos_dict.get(coordenada)
            
            fila_actual.append({
                'coordenada': coordenada,  
                'ocupado': bool(muestra_aqui),
                'muestra': muestra_aqui
            })
        cuadricula.append(fila_actual)

    return render(request, 'inventario/detalle_caja.html', {
        'caja': caja,
        'cuadricula': cuadricula
    })

@login_required
def crear_lote(request):
    if request.method == 'POST':
        form = RegistroIngresoForm(request.POST)
        if form.is_valid():
            form.save()
            # Al guardar el lote, la mandamos directo a ingresar las muestras
            return redirect('ingresar_muestra') 
    else:
        form = RegistroIngresoForm()
    
    return render(request, 'inventario/formulario_base.html', {'form': form, 'titulo': '📦 Abrir Nuevo Lote de Ingreso'})

@login_required
def crear_caja(request):
    if request.method == 'POST':
        form = CajaForm(request.POST)
        if form.is_valid():
            form.save()
            # Al guardar la caja, la mandamos directo a ingresar las muestras
            return redirect('ingresar_muestra')
    else:
        form = CajaForm()
    
    return render(request, 'inventario/formulario_base.html', {'form': form, 'titulo': '🧊 Crear Nueva Caja'})

# --- VISTAS AJAX REFORZADAS PARA MENÚS EN CASCADA ---

@login_required
def cargar_cajas(request):
    freezer_id = request.GET.get('freezer')
    
    # REGLA DE SEGURIDAD: Si el ID está vacío, devuelve el menú en blanco sin crashear
    if not freezer_id:
        return render(request, 'inventario/dropdown_opciones.html', {'opciones': [], 'tipo': 'caja'})
        
    cajas = Caja.objects.filter(rack__freezer_id=freezer_id).order_by('nombre')
    return render(request, 'inventario/dropdown_opciones.html', {'opciones': cajas, 'tipo': 'caja'})

@login_required
def cargar_huecos(request):
    caja_id = request.GET.get('caja')
    
    # REGLA DE SEGURIDAD: Si el ID está vacío, devuelve el menú en blanco sin crashear
    if not caja_id:
        return render(request, 'inventario/dropdown_opciones.html', {'opciones': [], 'tipo': 'hueco'})
        
    # Usamos try/except por si acaso hay un error con el nombre de las columnas (row/col)
    try:
        huecos = PosicionTubo.objects.filter(caja_id=caja_id, muestra__isnull=True).order_by('row', 'col')
    except Exception as e:
        print(f"Error al buscar huecos: {e}") # Esto te lo mostrará en tu terminal si algo falla
        huecos = PosicionTubo.objects.filter(caja_id=caja_id, muestra__isnull=True)
        
    return render(request, 'inventario/dropdown_opciones.html', {'opciones': huecos, 'tipo': 'hueco'})

@login_required
def registrar_salida(request):
    if request.method == 'POST':
        form = SalidaMuestraForm(request.POST)
        if form.is_valid():
            bsi_id = form.cleaned_data['bsi_id'].strip()
            
            try:
                # 1. Buscamos la muestra exacta
                muestra = MuestraBiologica.objects.get(bsi_id=bsi_id)
                
                # 2. Verificamos si la muestra ya fue sacada antes
                if not muestra.ubicacion:
                    messages.warning(request, f"La muestra {bsi_id} ya se encuentra fuera del freezer.")
                else:
                    # 3. Guardamos su ubicación actual como texto antes de borrarla
                    ubicacion_anterior = str(muestra.ubicacion)
                    
                    # 4. Creamos el registro histórico (Audit Trail)
                    movimiento = form.save(commit=False)
                    movimiento.muestra = muestra
                    movimiento.usuario = request.user  # Registra quién hizo el movimiento
                    movimiento.ubicacion_previa = ubicacion_anterior
                    movimiento.save()
                    
                    # 5. ¡MAGIA! Liberamos el hueco en la caja
                    muestra.ubicacion = None
                    muestra.vial_status = "Despachada/Consumida" # Actualizamos su estado
                    muestra.save()
                    
                    messages.success(request, f"¡Éxito! Salida registrada. El hueco de la muestra {bsi_id} ahora está vacío y disponible.")
                    return redirect('dashboard')
                    
            except MuestraBiologica.DoesNotExist:
                messages.error(request, f"Error: No existe ninguna muestra registrada con el ID '{bsi_id}'.")
    else:
        # Por defecto, seleccionamos la opción 'SALIDA'
        form = SalidaMuestraForm(initial={'tipo_movimiento': 'SALIDA'})

    # Usamos tu formulario_base.html para no tener que crear un HTML nuevo
    return render(request, 'inventario/formulario_base.html', {
        'form': form, 
        'titulo': '📤 Registrar Salida de Muestra'
    })

@login_required
def buscar_muestra(request):
    # 1. Capturamos todos los filtros que vengan en la URL
    query = request.GET.get('q', '').strip()
    material_id = request.GET.get('material', '')
    proyecto = request.GET.get('proyecto', '').strip()
    estudio_id = request.GET.get('estudio', '')

    # 2. Partimos con TODAS las muestras (Usamos select_related para que la base de datos vuele)
    muestras = MuestraBiologica.objects.select_related(
        'material_type', 'vial_type', 'ubicacion__caja__rack__freezer'
    ).all()

    # 3. Aplicamos los filtros uno por uno como si fueran coladores
    if query:
        # Busca si el texto coincide parcial o totalmente con BSI ID, Sample ID o Subject ID
        muestras = muestras.filter(
            Q(bsi_id__icontains=query) | 
            Q(sample_id__icontains=query) | 
            Q(subject_id__icontains=query)
        )
    
    if material_id:
        muestras = muestras.filter(material_type_id=material_id)
        
    if proyecto:
        muestras = muestras.filter(project__icontains=proyecto)
        
    if estudio_id:
        muestras = muestras.filter(study_id=estudio_id)

    # Ordenamos los resultados (ej: por Sample ID y luego por secuencia)
    muestras = muestras.order_by('sample_id', 'sequence')

    # 4. Preparamos las opciones para rellenar las cajitas de filtro en la pantalla
    materiales = TipoMaterial.objects.all().order_by('nombre')
    estudios = Estudio.objects.all().order_by('nombre_estudio')
    
    # Extraemos una lista de proyectos únicos que ya existen en la base de datos
    proyectos_unicos = MuestraBiologica.objects.values_list('project', flat=True)\
                        .exclude(project__isnull=True).exclude(project__exact='')\
                        .distinct().order_by('project')

    context = {
        'muestras': muestras,
        'query': query,
        'material_id': material_id,
        'proyecto_sel': proyecto,
        'estudio_id': estudio_id,
        'materiales': materiales,
        'estudios': estudios,
        'proyectos_unicos': proyectos_unicos,
        'total_resultados': muestras.count(),
    }
    
    return render(request, 'inventario/resultado_busqueda.html', context)

@login_required
@require_POST
def mover_muestra_ajax(request):
    try:
        # 1. Leemos los datos que envía el navegador al soltar el tubo
        data = json.loads(request.body)
        bsi_id = data.get('bsi_id')
        caja_id = data.get('caja_id')
        nueva_coord = data.get('nueva_coordenada') # Ej: "B5"

        if not all([bsi_id, caja_id, nueva_coord]):
            return JsonResponse({'success': False, 'error': 'Datos incompletos'})

        # 2. Separamos la letra del número (Ej: "B5" -> row="B", col=5)
        import re
        match = re.match(r"([a-zA-Z]+)(\d+)", nueva_coord)
        if not match:
            return JsonResponse({'success': False, 'error': 'Coordenada inválida'})
        
        row, col = match.groups()
        row = row.upper()
        col = int(col)

        # 3. Buscamos los objetos en la base de datos
        muestra = MuestraBiologica.objects.get(bsi_id=bsi_id)
        nueva_posicion = PosicionTubo.objects.get(caja_id=caja_id, row=row, col=col)

        # 4. Verificamos que el hueco destino esté realmente vacío
        if hasattr(nueva_posicion, 'muestra') and nueva_posicion.muestra:
            return JsonResponse({'success': False, 'error': 'El hueco de destino ya está ocupado'})

        ubicacion_anterior = str(muestra.ubicacion)

        # 5. ¡Actualizamos la posición!
        muestra.ubicacion = nueva_posicion
        muestra.save()

        # 6. Dejamos el registro en la Auditoría (Trazabilidad perfecta)
        MovimientoMuestra.objects.create(
            muestra=muestra,
            tipo_movimiento='REUBICACION',
            usuario=request.user,
            motivo=f'Reubicación interna mediante Drag & Drop a {nueva_coord}',
            ubicacion_previa=ubicacion_anterior
        )

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
    
@login_required
def escaner_movil(request):
    # Solo renderiza la página con la cámara
    return render(request, 'inventario/escaner_movil.html')