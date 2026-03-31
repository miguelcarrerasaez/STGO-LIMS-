from django.shortcuts import render, redirect, get_object_or_404
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required # 1. Importamos el "guardia de seguridad"
from django.contrib.admin.views.decorators import staff_member_required
import csv
from .models import MuestraBiologica, Rack, Caja, RegistroIngreso, Freezer, PosicionTubo
from .forms import MuestraBiologicaForm, RegistroIngresoForm, CajaForm

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
    # 1. Hacemos consultas a la base de datos
    total_muestras = MuestraBiologica.objects.count()
    total_racks = Rack.objects.count()
    total_cajas = Caja.objects.count()
    
    # Obtenemos los últimos 5 lotes ingresados, ordenados por fecha descendente
    ultimos_ingresos = RegistroIngreso.objects.order_by('-fecha_ingreso')[:5]

    # 2. Empaquetamos los datos en un "contexto" (un diccionario de Python)
    context = {
        'total_muestras': total_muestras,
        'total_racks': total_racks,
        'total_cajas': total_cajas,
        'ultimos_ingresos': ultimos_ingresos,
    }

    # 3. Se lo enviamos al archivo HTML para que lo dibuje
    return render(request, 'inventario/dashboard.html', context)

@staff_member_required
def exportar_inventario_csv(request):
    # 1. Le decimos al navegador: "Prepárate, te voy a enviar un archivo CSV, no una página web"
    response = HttpResponse(content_type='text/csv')
    
    # 2. Forzamos la descarga y le ponemos un nombre al archivo
    response['Content-Disposition'] = 'attachment; filename="reporte_muestras_lims.csv"'

    # 3. Creamos el "escritor" de CSV de Python, apuntándolo a nuestra respuesta
    writer = csv.writer(response)

    # 4. Escribimos la primera fila (Los encabezados de las columnas)
    writer.writerow([
        'BSI ID', 
        'Sample ID', 
        'Tipo de Material', 
        'Estado', 
        'Lote de Ingreso', 
        'Código Interno (SYS)',
        'Fecha de Registro'
    ])

    # 5. Traemos todas las muestras de la base de datos
    # select_related optimiza la búsqueda para traer los datos del lote asociado súper rápido
    muestras = MuestraBiologica.objects.all().select_related('entry_batch')

    # 6. Recorremos las muestras una por una y escribimos las filas
    for muestra in muestras:
        # Si la muestra tiene un lote asignado, sacamos sus nombres, si no, lo dejamos en blanco
        nombre_lote = muestra.entry_batch.codigo_lote if muestra.entry_batch else "Sin Lote"
        codigo_sys = muestra.entry_batch.registro_interno if muestra.entry_batch else ""
        
        # Formateamos la fecha para que se vea bien en Excel
        fecha = muestra.date_entered.strftime("%d/%m/%Y %H:%M") if muestra.date_entered else ""
        
        writer.writerow([
            muestra.bsi_id,
            muestra.sample_id,
            muestra.material_type,
            muestra.vial_status,
            nombre_lote,
            codigo_sys,
            fecha
        ])

    return response

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