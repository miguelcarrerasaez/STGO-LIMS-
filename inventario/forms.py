from django import forms
from .models import MuestraBiologica, PosicionTubo, RegistroIngreso, Caja, Rack, Freezer, MovimientoMuestra

class MuestraBiologicaForm(forms.ModelForm):
    class Meta:
        model = MuestraBiologica
        fields = '__all__'
        
        # --- NUEVO: Activamos los calendarios nativos del navegador ---
        widgets = {
            'date_drawn': forms.DateInput(attrs={'type': 'date'}),
            'date_received': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 1. Creamos campos "virtuales" al vuelo para filtrar
        self.fields['freezer'] = forms.ModelChoiceField(
            queryset=Freezer.objects.all(), required=False, empty_label="1. Seleccione un Freezer..."
        )
        self.fields['caja'] = forms.ModelChoiceField(
            queryset=Caja.objects.none(), required=False, empty_label="2. Esperando freezer..."
        )

        # 2. Ordenamos: Mandamos el campo Ubicacion al final de la lista
        if 'ubicacion' in self.fields:
            ubicacion_field = self.fields.pop('ubicacion')
            self.fields['ubicacion'] = ubicacion_field
            self.fields['ubicacion'].queryset = PosicionTubo.objects.none()
            self.fields['ubicacion'].empty_label = "3. Esperando caja..."

        # 3. Diseño Bootstrap
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select shadow-sm'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control shadow-sm'
        
        # 4. LA MAGIA HTMX: Conectamos los cables entre los menús
        self.fields['freezer'].widget.attrs.update({
            'hx-get': '/ajax/cargar-cajas/', # Qué ruta llamar
            'hx-target': '#id_caja'          # A quién actualizar
        })
        self.fields['caja'].widget.attrs.update({
            'hx-get': '/ajax/cargar-huecos/',
            'hx-target': '#id_ubicacion'
        })
        if 'freezer' in self.data:
            try:
                freezer_id = int(self.data.get('freezer'))
                # Le damos permiso a Django de aceptar las cajas de este freezer
                self.fields['caja'].queryset = Caja.objects.filter(rack__freezer_id=freezer_id)
            except (ValueError, TypeError):
                pass
                
        if 'caja' in self.data:
            try:
                caja_id = int(self.data.get('caja'))
                # Le damos permiso a Django de aceptar los huecos de esta caja
                self.fields['ubicacion'].queryset = PosicionTubo.objects.filter(caja_id=caja_id)
            except (ValueError, TypeError):
                pass

# --- NUEVO: Formulario para crear el Lote de Ingreso ---
class RegistroIngresoForm(forms.ModelForm):
    class Meta:
        model = RegistroIngreso
        fields = '__all__'
        widgets = {
            'fecha_recepcion': forms.DateInput(attrs={'type': 'date'}), # Calendario nativo
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select shadow-sm'
            else:
                field.widget.attrs['class'] = 'form-control shadow-sm'

# --- NUEVO: Formulario para crear una Caja nueva ---
class CajaForm(forms.ModelForm):
    class Meta:
        model = Caja
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select shadow-sm'
            else:
                field.widget.attrs['class'] = 'form-control shadow-sm'

class SalidaMuestraForm(forms.ModelForm):
    # Campo extra para escanear el código de barras/QR
    bsi_id = forms.CharField(
        label="BSI ID de la Muestra", 
        max_length=50, 
        help_text="Escanea o escribe el código de la muestra"
    )

    class Meta:
        model = MovimientoMuestra
        fields = ['tipo_movimiento', 'motivo', 'destino']
        widgets = {
            'motivo': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ej: Extracción de ADN para secuenciación...'}),
        }

class ExportarCSVForm(forms.Form):
    OPCIONES_EXPORTACION = [
        ('bsi_id', 'BSI ID'),
        ('sample_id', 'Sample ID'),
        ('project', 'Proyecto / Sub-estudio'),
        ('subject_id', 'ID de Paciente (Subject ID)'),
        ('material_type', 'Tipo de Material'),
        ('vial_type', 'Tipo de Vial'),
        ('vial_status', 'Estado de la Muestra'),
        ('volume', 'Volumen'),
        ('thaws', 'Ciclos de Descongelamiento'),
        ('hemolyzed', 'Hemolizada (Sí/No)'),
        ('date_drawn', 'Fecha de Extracción'),
        ('date_received', 'Fecha de Recepción'),
        ('ubicacion_fisica', 'Ubicación Física Completa (Freezer > Caja > Hueco)'),
        ('entry_batch', 'Código del Lote de Ingreso'),
    ]

    columnas = forms.MultipleChoiceField(
        choices=OPCIONES_EXPORTACION,
        widget=forms.CheckboxSelectMultiple,
        label="1. Selecciona las columnas a incluir:",
        required=True,
        initial=['bsi_id', 'sample_id', 'material_type', 'vial_status', 'ubicacion_fisica'] 
    )

    # 2. LOS NUEVOS FILTROS (Son opcionales)
    freezer = forms.ModelChoiceField(
        queryset=Freezer.objects.all(),
        required=False,
        empty_label="--- Todos los Equipos ---",
        label="2. Filtrar por Equipo (Opcional)"
    )
    
    rack = forms.ModelChoiceField(
        queryset=Rack.objects.all(),
        required=False,
        empty_label="--- Todos los Racks ---",
        label="3. Filtrar por Rack (Opcional)"
    )
    
    caja = forms.ModelChoiceField(
        queryset=Caja.objects.all(),
        required=False,
        empty_label="--- Todas las Cajas ---",
        label="4. Filtrar por Caja Específica (Opcional)"
    )