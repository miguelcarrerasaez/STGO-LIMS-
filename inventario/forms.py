from django import forms
from .models import MuestraBiologica, PosicionTubo, RegistroIngreso, Caja, Freezer

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