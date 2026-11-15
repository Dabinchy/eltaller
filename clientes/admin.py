"""
Admin de clientes.

- Clientes: alta y edición con los permisos estándar; borrado físico sólo superusuario.
- Cuenta corriente: sólo lectura (el saldo lo mueven los movimientos).
- Movimientos: se pueden REGISTRAR con clientes.movimientos_cc; nunca editar ni borrar.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin

from .models import Cliente, CuentaCorriente, MovimientoCuentaCorriente

PERM_MOVIMIENTOS_CC = "clientes.movimientos_cc"


# ============================================================
# Clientes
# ============================================================

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "doc_tipo", "doc_numero", "telefono", "email", "limite_credito", "saldo", "activo")
    list_filter = ("activo", "doc_tipo")
    search_fields = ("nombre", "doc_numero", "email", "telefono")
    readonly_fields = ("saldo", "created_at", "updated_at")
    filter_horizontal = ("listas_autorizadas",)
    fieldsets = (
        (None, {"fields": ("nombre", "activo")}),
        ("Documento", {"fields": ("doc_tipo", "doc_numero")}),
        ("Contacto", {"fields": ("telefono", "email", "direccion")}),
        ("Cuenta corriente y precios", {"fields": ("limite_credito", "saldo", "listas_autorizadas")}),
        (
            "Fiscal (sin uso)",
            {"classes": ("collapse",), "fields": ("condicion_iva", "es_consumidor_final")},
        ),
        ("Auditoría", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("cuenta_corriente")

    @admin.display(description="Saldo CC")
    def saldo(self, obj):
        return obj.saldo_cc

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("delete_selected", None)
        return actions


# ============================================================
# Cuenta corriente (sólo lectura)
# ============================================================

class MovimientoCCInline(admin.TabularInline):
    model = MovimientoCuentaCorriente
    extra = 0
    can_delete = False
    fields = ("fecha", "tipo", "monto", "descripcion", "creado_por", "creado_el")
    readonly_fields = fields
    ordering = ("-fecha", "-id")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CuentaCorriente)
class CuentaCorrienteAdmin(admin.ModelAdmin):
    list_display = ("cliente", "saldo", "actualizado_el")
    search_fields = ("cliente__nombre", "cliente__doc_numero")
    readonly_fields = ("cliente", "saldo", "actualizado_el")
    list_select_related = ("cliente",)
    inlines = [MovimientoCCInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ============================================================
# Movimientos de cuenta corriente
# ============================================================

class MovimientoCCAdminForm(forms.ModelForm):
    class Meta:
        model = MovimientoCuentaCorriente
        fields = ("cuenta", "tipo", "monto", "fecha", "descripcion")

    def clean(self):
        datos = super().clean()
        cuenta, tipo, monto = datos.get("cuenta"), datos.get("tipo"), datos.get("monto")
        # Aviso amable antes de llegar al modelo (que igual lo rechaza).
        if cuenta and monto and tipo == MovimientoCuentaCorriente.Tipo.CREDITO and monto > cuenta.saldo:
            raise forms.ValidationError(
                f"El pago ({monto}) supera la deuda actual del cliente ({cuenta.saldo})."
            )
        return datos


@admin.register(MovimientoCuentaCorriente)
class MovimientoCCAdmin(admin.ModelAdmin):
    form = MovimientoCCAdminForm
    list_display = ("fecha", "cuenta", "tipo", "monto", "descripcion", "creado_por")
    list_filter = ("tipo",)
    search_fields = ("cuenta__cliente__nombre", "cuenta__cliente__doc_numero", "descripcion")
    list_select_related = ("cuenta__cliente", "creado_por")
    autocomplete_fields = ("cuenta",)
    date_hierarchy = "fecha"

    def get_readonly_fields(self, request, obj=None):
        if obj:  # un movimiento guardado se ve completo, sin editar
            return ("cuenta", "tipo", "monto", "fecha", "descripcion", "creado_por", "creado_el")
        return ()

    def save_model(self, request, obj, form, change):
        obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.has_perm(PERM_MOVIMIENTOS_CC)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
