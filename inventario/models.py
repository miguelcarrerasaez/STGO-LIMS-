from django.db import models
import uuid
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User # <- IMPORTACIÓN NECESARIA PARA LA AUDITORÍA

class Estudio(models.Model):
    nombre_estudio = models.CharField(max_length=100, help_text="Ej: DAVOS")
    investigador_principal = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.nombre_estudio

class Freezer(models.Model):
    nombre = models.CharField(verbose_name=_("Nombre del Equipo"), max_length=50, help_text=_("Ej: Ultracongelador 1"))
    modelo = models.CharField(verbose_name=_("Modelo/Marca"), max_length=50, blank=True, help_text=_("Ej: Thermo Scientific Revco"))
    temperatura = models.CharField(verbose_name=_("Temperatura de Operación"), max_length=20, default="-80°C")
    ubicacion = models.CharField(verbose_name=_("Ubicación Física"), max_length=100, blank=True, help_text=_("Ej: Sala 2, Pasillo A"))

    def __str__(self):
        return f"{self.nombre} ({self.temperatura})"

    # ▼▼▼ NUEVO CÁLCULO INTELIGENTE ▼▼▼
    def capacidad_maxima_tubos(self):
        # El freezer suma la capacidad máxima exacta de cada rack que tiene adentro
        return sum(rack.capacidad_maxima() for rack in self.racks.all())

    def posiciones_ocupadas(self):
        from .models import PosicionTubo
        return PosicionTubo.objects.filter(caja__rack__freezer=self, muestra__isnull=False).count()

    def porcentaje_ocupacion(self):
        capacidad = self.capacidad_maxima_tubos()
        if capacidad <= 0:
            return 0
        porcentaje = (self.posiciones_ocupadas() / capacidad) * 100
        return min(int(porcentaje), 100)

class Rack(models.Model):
    freezer = models.ForeignKey(Freezer, on_delete=models.CASCADE, related_name="racks", verbose_name=_("Freezer Asignado"))    
    nombre = models.CharField(max_length=50, help_text="Ej: Rack A1")
    filas_alto = models.IntegerField(help_text="Cantidad de cajas hacia arriba (ej: 5, 7)")
    columnas_ancho = models.IntegerField(help_text="Cantidad de cajas hacia el lado (ej: 5, 4)")
    
    # Nuevo campo para los racks variables (4x4 o 5x5)
    tubos_por_caja_estandar = models.IntegerField(
        default=100, 
        help_text="100 para criocajas 10x10, 81 para criocajas 9x9"
    )

    # ▼▼▼ TU REGLA DE ORO FÍSICA ▼▼▼
    def capacidad_maxima(self):
        if self.filas_alto == 7 and self.columnas_ancho == 5:
            # Regla estricta: 7x5 SIEMPRE usa cajas 10x10 (100 posiciones)
            return 7 * 5 * 100
        else:
            # Para 4x4 o 5x5, usa la configuración asignada a este rack específico
            return self.filas_alto * self.columnas_ancho * self.tubos_por_caja_estandar

    def __str__(self):
        return f"{self.nombre} ({self.columnas_ancho}x{self.filas_alto}) - {self.freezer.nombre}"

class Caja(models.Model):
    rack = models.ForeignKey(Rack, on_delete=models.CASCADE, related_name="cajas")
    codigo_caja = models.CharField(max_length=50, blank=True)
    nombre = models.CharField(max_length=50)
    
    posicion_fila_en_rack = models.IntegerField()
    posicion_columna_en_rack = models.IntegerField()
    
    filas_de_caja = models.IntegerField(default=9, help_text="Ej: 9 para cajas estándar, 10 para cajas de 100")
    columnas_de_caja = models.IntegerField(default=9, help_text="Ej: 9, 10, etc.")

    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)
        
        if es_nuevo:
            posiciones_a_crear = []
            letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            
            for f in range(self.filas_de_caja):
                letra_fila = letras[f] if f < len(letras) else str(f)
                for c in range(1, self.columnas_de_caja + 1):
                    nueva_posicion = PosicionTubo(
                        caja=self,
                        row=letra_fila,
                        col=c
                    )
                    posiciones_a_crear.append(nueva_posicion)
            PosicionTubo.objects.bulk_create(posiciones_a_crear)

    def __str__(self):
        nombre_mostrar = self.codigo_caja if self.codigo_caja else self.nombre
        return f"Caja {nombre_mostrar} ({self.columnas_de_caja}x{self.filas_de_caja}) - {self.rack.nombre}"
    
class RegistroIngreso(models.Model):
    codigo_lote = models.CharField(
        verbose_name=_("Código de Lote (Manual)"), 
        max_length=100, 
        unique=True,
        help_text=_("Ej: LOTE-DAVOS-001")
    )
    
    registro_interno = models.CharField(
        verbose_name=_("Registro Interno (Sistema)"), 
        max_length=100, 
        unique=True, 
        blank=True, 
        editable=False
    )
    
    fecha_ingreso = models.DateTimeField(
        verbose_name=_("Fecha de Ingreso"), 
        auto_now_add=True
    )

    def save(self, *args, **kwargs):
        if not self.registro_interno:
            fecha = timezone.now().strftime("%Y%m%d")
            codigo_unico = str(uuid.uuid4()).split('-')[0].upper()
            self.registro_interno = f"SYS-IN-{fecha}-{codigo_unico}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo_lote} (Ref: {self.registro_interno})"

class TipoMaterial(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self): return self.nombre

class TipoVial(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    def __str__(self): return self.nombre

class MuestraBiologica(models.Model):
    bsi_id = models.CharField(max_length=50, primary_key=True, unique=True)
    sample_id = models.CharField(max_length=50)
    sequence = models.IntegerField(default=1)
    
    study = models.ForeignKey(Estudio, on_delete=models.SET_NULL, null=True, blank=True)    
    project = models.CharField(max_length=100, null=True, blank=True, help_text="Proyecto específico (Ej: Sub-proyecto de DAVOS)")
    
    subject_id = models.CharField(max_length=100, null=True, blank=True, help_text="ID anonimizado del paciente/participante")
    parent_id = models.CharField(max_length=50, null=True, blank=True, help_text="BSI ID de la muestra original (si es alícuota)")

    material_type = models.ForeignKey(TipoMaterial, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Tipo de Material")
    vial_type = models.ForeignKey(TipoVial, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Tipo de Vial")
    vial_status = models.CharField(max_length=50, default="Disponible")
    
    volume = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, help_text="Volumen de la muestra (ej: 500.000)")
    volume_unit = models.CharField(max_length=20, null=True, blank=True, help_text="Unidad de medida (ej: µL, mL)")
    thaws = models.IntegerField(default=0, help_text="Número de ciclos de descongelamiento")
    hemolyzed = models.BooleanField(default=False, verbose_name="Hemolizada")
    vial_warnings = models.TextField(null=True, blank=True, help_text="Advertencias o notas sobre la calidad del vial")

    date_drawn = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de Extracción")
    date_received = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de Recepción")
    date_frozen = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de Congelación")
    date_entered = models.DateTimeField(auto_now_add=True)
    
    entry_batch = models.ForeignKey(
        'RegistroIngreso', 
        on_delete=models.CASCADE, 
        verbose_name=_("Lote de Ingreso"), 
        null=True, 
        blank=True
    )
    ubicacion = models.OneToOneField(
        'PosicionTubo', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='muestra',
        verbose_name="Ubicación en Caja (Hueco)"
    )

    def __str__(self):
        return f"BSI: {self.bsi_id} | Sample: {self.sample_id}"
    
class PosicionTubo(models.Model):
    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name="posiciones")
    row = models.CharField(max_length=5, help_text="Fila (Ej: A, B, C)")
    col = models.IntegerField(help_text="Columna (Ej: 1, 2, 3)")

    def __str__(self):
        nombre_caja = self.caja.codigo_caja if self.caja.codigo_caja else self.caja.nombre
        return f"Caja {nombre_caja} - Posición {self.row}{self.col}"

# ▼▼▼ ESTE ES EL NUEVO MODELO QUE FALTABA PARA LA AUDITORÍA ▼▼▼
class MovimientoMuestra(models.Model):
    TIPOS_MOVIMIENTO = [
        ('SALIDA', 'Salida de Freezer (Consumo/Envío)'),
        ('RETORNO', 'Retorno a Freezer'),
        ('REUBICACION', 'Reubicación Interna'),
        ('AUDITORIA', 'Revisión de Auditoría (Inventario)'),
    ]

    muestra = models.ForeignKey(MuestraBiologica, on_delete=models.CASCADE, related_name='historial_movimientos')
    tipo_movimiento = models.CharField(max_length=20, choices=TIPOS_MOVIMIENTO)
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, help_text="Usuario que registró el movimiento")
    fecha_movimiento = models.DateTimeField(auto_now_add=True)
    
    motivo = models.TextField(help_text="Ej: Extracción de ADN, Envío a laboratorio externo, etc.")
    destino = models.CharField(max_length=100, blank=True, null=True, help_text="Lugar o persona que recibe la muestra")
    
    ubicacion_previa = models.CharField(max_length=100, blank=True, null=True, help_text="Queda guardado como texto por si la caja original se borra")

    def __str__(self):
        return f"{self.muestra.bsi_id} - {self.tipo_movimiento} ({self.fecha_movimiento.strftime('%d/%m/%Y')})"