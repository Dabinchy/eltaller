# core/admin.py
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.utils.translation import gettext_lazy as _

from .models import Caja, CajaMovimiento, Empresa, SesionCaja, Sucursal, Usuario


# ============================================================
# Roles y alcance por sucursal
# ============================================================

GRUPO_GERENTE = "gerente"
GRUPO_JEFE = "jefe"
GRUPO_ADMINISTRACION = "administracion"

def _es_gerente(user) -> bool:
    """Gerente: superusuario, permiso core.administrar_core o grupo 'gerente'."""
    if getattr(user, "es_portal", False):
        return False
    return bool(
        user.is_superuser
        or user.has_perm("core.administrar_core")
        or user.groups.filter(name=GRUPO_GERENTE).exists()
    )


def _es_jefe(user) -> bool:
    """ Personal que opera la caja y ve su estructura (sucursales, cajas, sesiones):
    gerente, jefe, administración, o cualquiera con el permiso core.movimientos_caja.
    """
    if getattr(user, "es_portal", False):
        return False
    return bool(
        _es_gerente(user)
        or user.has_perm("core.movimientos_caja")
        or user.groups.filter(name__in=(GRUPO_JEFE, GRUPO_ADMINISTRACION)).exists()

    )


def _filtrar_por_sucursal(qs, user, campo: str):
    """
    Gerente y superusuario ven todas las sucursales.
    El resto sólo ve su sucursal fija (y si no tiene, no ve nada).
    `campo` es el lookup hacia la sucursal: 'pk', 'sucursal_id', 'caja__sucursal_id'...
    """
    if user.is_superuser or _es_gerente(user):
        return qs
    sid = getattr(user, "sucursal_id", None)
    if not sid:
        return qs.none()
    return qs.filter(**{campo: sid})


def _verificar_sucursal_o_403(user, sucursal_id) -> None:
    """Evita abrir por URL directa un objeto de otra sucursal."""
    if user.is_superuser or _es_gerente(user):
        return
    sid = getattr(user, "sucursal_id", None)
    if not sid or sucursal_id != sid:
        raise PermissionDenied("Acceso denegado (sucursal).")


# ============================================================
# Empresa (una sola fila)
# ============================================================

@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "telefono", "whatsapp", "localidad", "activa")
    fieldsets = (
        ("Datos del taller", {
            "fields": ("nombre", "razon_social", "descripcion_web", "logo", "activa"),
        }),
        ("Contacto", {
            "fields": ("telefono", "whatsapp", "email_contacto", "horarios"),
        }),
        ("Redes y mapa (se muestran en el sitio)", {
            "fields": ("instagram", "facebook", "youtube", "mapa_url"),
        }),
        ("Dirección", {
            "fields": ("direccion", "localidad", "provincia", "codigo_postal", "pais"),
        }),
        ("Datos fiscales (opcional)", {
            "classes": ("collapse",),
            "fields": ("cuit", "condicion_iva", "iibb_numero", "domicilio_comercial", "inicio_actividades"),
        }),
        ("AFIP (sin uso por ahora)", {
            "classes": ("collapse",),
            "fields": ("afip_modo", "afip_punto_venta_default", "afip_cert_alias"),
        }),
    )

    def has_module_permission(self, request):
        return _es_gerente(request.user)

    def has_view_permission(self, request, obj=None):
        return _es_gerente(request.user)

    def has_change_permission(self, request, obj=None):
        return _es_gerente(request.user)

    def has_add_permission(self, request):
        # Sólo el superusuario, y sólo si todavía no existe la empresa.
        return request.user.is_superuser and not Empresa.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # El sistema necesita su empresa: no se borra desde el admin.
        return False


# ============================================================
# Sucursal
# ============================================================

@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("nombre", "direccion", "cupo", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre", "direccion")
    ordering = ("nombre",)

    @admin.display(description="Cupo de turnos")
    def cupo(self, obj):
        return obj.cupo_turnos if obj.cupo_turnos is not None else "Sin límite"

    def has_module_permission(self, request):
        return _es_jefe(request.user)

    def get_queryset(self, request):
        return _filtrar_por_sucursal(super().get_queryset(request), request.user, "pk")

    def has_view_permission(self, request, obj=None):
        if not _es_jefe(request.user):
            return False
        if obj is not None:
            _verificar_sucursal_o_403(request.user, obj.pk)
        return True

    def has_add_permission(self, request):
        return _es_gerente(request.user)

    def has_change_permission(self, request, obj=None):
        return _es_gerente(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================
# Caja
# ============================================================

class CajaSesionAbiertaFilter(admin.SimpleListFilter):
    title = "sesión abierta"
    parameter_name = "sesion_abierta"

    def lookups(self, request, model_admin):
        return (("si", "Sí"), ("no", "No"))

    def queryset(self, request, qs):
        abierta = SesionCaja.objects.filter(caja=OuterRef("pk"), estado=SesionCaja.Estado.ABIERTA)
        qs = qs.annotate(has_open_session=Exists(abierta))
        if self.value() == "si":
            return qs.filter(has_open_session=True)
        if self.value() == "no":
            return qs.filter(has_open_session=False)
        return qs


@admin.register(Caja)
class CajaAdmin(admin.ModelAdmin):
    list_display = ("id", "sucursal", "numero", "nombre", "activa", "sesion_abierta")
    list_filter = ("sucursal", "activa", CajaSesionAbiertaFilter)
    search_fields = ("sucursal__nombre", "numero", "nombre")
    ordering = ("sucursal__nombre", "numero")
    readonly_fields = ("numero",)

    def has_module_permission(self, request):
        return _es_jefe(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("sucursal")
        abierta = SesionCaja.objects.filter(caja=OuterRef("pk"), estado=SesionCaja.Estado.ABIERTA)
        qs = qs.annotate(has_open_session=Exists(abierta))
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            ro.append("sucursal")  # una caja no se "muda" de sucursal
        return ro

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal":
            kwargs["queryset"] = _filtrar_por_sucursal(Sucursal.objects.all(), request.user, "pk")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(boolean=True, description="¿Abierta?")
    def sesion_abierta(self, obj):
        return bool(getattr(obj, "has_open_session", False))

    def has_view_permission(self, request, obj=None):
        if not _es_jefe(request.user):
            return False
        if obj is not None:
            _verificar_sucursal_o_403(request.user, obj.sucursal_id)
        return True

    def has_add_permission(self, request):
        return _es_gerente(request.user)

    def has_change_permission(self, request, obj=None):
        return _es_gerente(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================
# Sesión de caja (sólo lectura; auditoría)
# ============================================================

class CajaMovimientoInline(admin.TabularInline):
    model = CajaMovimiento
    extra = 0
    can_delete = False
    fields = ("tipo", "monto", "motivo", "creado_por", "creado_el")
    readonly_fields = ("tipo", "monto", "motivo", "creado_por", "creado_el")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SesionCaja)
class SesionCajaAdmin(admin.ModelAdmin):
    list_display = (
        "id", "caja", "estado", "abierta_el", "cerrada_el",
        "abierta_por", "cerrada_por", "saldo_inicial", "saldo_estimado", "saldo_cierre",
    )
    list_filter = ("estado", "caja__sucursal", "caja")
    search_fields = ("caja__sucursal__nombre", "abierta_por__username", "cerrada_por__username")
    date_hierarchy = "abierta_el"
    ordering = ("-abierta_el",)
    readonly_fields = (
        "caja", "estado", "abierta_el", "cerrada_el", "abierta_por", "cerrada_por",
        "ip_apertura", "ip_cierre", "terminal", "saldo_inicial", "saldo_estimado",
        "saldo_cierre", "total_efectivo_contado", "diferencia", "observacion_cierre",
    )
    inlines = [CajaMovimientoInline]

    def has_module_permission(self, request):
        return _es_jefe(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "caja", "caja__sucursal", "abierta_por", "cerrada_por",
        )
        return _filtrar_por_sucursal(qs, request.user, "caja__sucursal_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        if not _es_jefe(request.user):
            return False
        if obj is not None:
            _verificar_sucursal_o_403(request.user, obj.caja.sucursal_id)
        return True

    def has_change_permission(self, request, obj=None):
        # Se puede abrir el detalle, pero no hay campos editables.
        return self.has_view_permission(request, obj)


# ============================================================
# Movimiento de caja (sólo consulta; auditoría)
# ============================================================

@admin.register(CajaMovimiento)
class CajaMovimientoAdmin(admin.ModelAdmin):
    list_display = ("id", "caja", "sesion", "tipo", "monto", "creado_por", "creado_el")
    list_filter = ("tipo", "caja__sucursal", "caja")
    search_fields = ("caja__sucursal__nombre", "sesion__id", "motivo", "creado_por__username")
    ordering = ("-creado_el",)
    readonly_fields = ("caja", "sesion", "tipo", "monto", "motivo", "creado_por", "creado_el")

    def has_module_permission(self, request):
        return _es_jefe(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "caja", "caja__sucursal", "sesion", "creado_por",
        )
        return _filtrar_por_sucursal(qs, request.user, "caja__sucursal_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # los movimientos son inmutables (auditoría)

    def has_view_permission(self, request, obj=None):
        if not _es_jefe(request.user):
            return False
        if obj is not None:
            _verificar_sucursal_o_403(request.user, obj.caja.sucursal_id)
        return True

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)


# ============================================================
# Usuario (personal y usuarios del portal)
# ============================================================

@admin.action(description="Desbloquear PIN seleccionado(s)")
def desbloquear_pin(modeladmin, request, queryset):
    if not _es_gerente(request.user):
        raise PermissionDenied("Sólo gerente/superusuario puede desbloquear PIN.")
    queryset.update(pin_failed_attempts=0, pin_locked_until=None)


class _ReglasUsuarioMixin:
    """Reglas que se validan al crear y al editar un usuario desde el admin."""

    def _validar_reglas_usuario(self, cleaned):
        request = getattr(self, "request", None)
        actor = getattr(request, "user", None)

        tipo = cleaned.get("tipo")
        sucursal = cleaned.get("sucursal")
        groups = cleaned.get("groups")
        tiene_grupos = groups is not None and groups.exists()

        if tipo == Usuario.Tipo.PORTAL:
            if sucursal:
                self.add_error("sucursal", "Un usuario del portal no tiene sucursal fija.")
            if tiene_grupos:
                self.add_error("groups", "Un usuario del portal no puede tener roles del personal.")
            if cleaned.get("is_staff"):
                self.add_error("is_staff", "Un usuario del portal no puede entrar al administrador.")
            if cleaned.get("is_superuser"):
                self.add_error("is_superuser", "Un usuario del portal no puede ser superusuario.")

        elif tipo == Usuario.Tipo.STAFF:
            es_gerente_destino = groups is not None and groups.filter(name=GRUPO_GERENTE).exists()
            if not sucursal and not es_gerente_destino and not cleaned.get("is_superuser"):
                self.add_error(
                    "sucursal",
                    "La sucursal es obligatoria para el personal que no es gerente.",
                )

        # Quien no es superusuario no puede escalar privilegios.
        if actor is not None and not actor.is_superuser:
            if cleaned.get("is_superuser"):
                self.add_error("is_superuser", "No puede asignar superusuario.")
            perms = cleaned.get("user_permissions")
            if perms is not None and perms.exists():
                self.add_error("user_permissions", "Asigne permisos por grupos, no permisos directos.")


class UsuarioAdminCreationForm(_ReglasUsuarioMixin, UserCreationForm):
    """Alta: usa password1/password2 (la contraseña se guarda con hash)."""

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = (
            "username", "first_name", "last_name", "email", "dni",
            "tipo", "sucursal", "is_active", "is_staff", "groups",
        )

    def clean(self):
        cleaned = super().clean()
        self._validar_reglas_usuario(cleaned)
        return cleaned


class UsuarioAdminChangeForm(_ReglasUsuarioMixin, UserChangeForm):
    """Edición: mantiene el campo de contraseña de sólo lectura (hash)."""

    def clean(self):
        cleaned = super().clean()
        self._validar_reglas_usuario(cleaned)
        return cleaned


@admin.register(Usuario)
class UsuarioAdmin(DjangoUserAdmin):
    form = UsuarioAdminChangeForm
    add_form = UsuarioAdminCreationForm
    actions = [desbloquear_pin]

    list_display = (
        "username", "email", "tipo", "sucursal", "is_staff", "is_active",
        "pin_failed_attempts", "pin_locked_until", "pin_configurado",
    )
    list_filter = ("tipo", "sucursal", "is_staff", "is_active", "groups")
    search_fields = ("username", "first_name", "last_name", "email", "dni")
    ordering = ("username",)

    @admin.display(boolean=True, description="PIN set")
    def pin_configurado(self, obj: Usuario) -> bool:
        return bool(obj.action_pin_hash)

    def has_module_permission(self, request):
        return _es_gerente(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("sucursal")
        if not request.user.is_superuser:
            qs = qs.exclude(is_superuser=True)  # un gerente no ve ni edita superusuarios
        return qs

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        form.request = request  # para validar las reglas según quién edita
        return form

    def get_fieldsets(self, request, obj=None):
        personal = (_("Personal info"), {"fields": ("first_name", "last_name", "email", "dni")})
        ubicacion = (_("Tipo y ubicación"), {"fields": ("tipo", "sucursal")})

        if request.user.is_superuser:
            campos_permisos = ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")
        else:
            campos_permisos = ("is_active", "is_staff", "groups")
        permisos = (_("Permissions"), {"fields": campos_permisos})

        if obj is None:  # alta
            return (
                (None, {"fields": ("username", "password1", "password2")}),
                personal,
                ubicacion,
                permisos,
            )

        return (  # edición
            (None, {"fields": ("username", "password")}),
            personal,
            ubicacion,
            permisos,
            (_("Important dates"), {"fields": ("last_login", "date_joined")}),
            (_("Seguridad (PIN)"), {"fields": ("pin_failed_attempts", "pin_locked_until")}),
        )

    def get_readonly_fields(self, request, obj=None):
        # El PIN nunca se edita desde el admin (sólo desde el flujo de la aplicación).
        return [
            "pin_failed_attempts", "pin_locked_until", "last_login", "date_joined",
            "action_pin_hash", "action_pin_fingerprint",
        ]

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if not _es_gerente(request.user):
                raise PermissionDenied("Sólo gerente/superusuario puede administrar usuarios.")
            obj.is_superuser = False  # nunca permitir escalada
        super().save_model(request, obj, form, change)

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if not _es_gerente(request.user):
            return False
        return obj is None or not obj.is_superuser

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return _es_gerente(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser