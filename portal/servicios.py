"""
Operaciones de moderación del portal. Cada una verifica permisos y queda en el historial.

Las vistas (paso 5) y el admin llaman a estas funciones; nunca cambian estados a mano.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from taller.permisos import es_gerente

from . import permisos
from .models import AccesoCliente, Asociacion, Membresia, PerfilPiloto, RegistroModeracion

A = RegistroModeracion.Accion
E = Membresia.Estado


def registrar(actor, accion: str, objeto, asociacion=None, motivo: str = "") -> RegistroModeracion:
    return RegistroModeracion.objects.create(
        actor=actor,
        accion=accion,
        content_type=ContentType.objects.get_for_model(objeto),
        object_id=objeto.pk,
        descripcion_objeto=str(objeto)[:200],
        asociacion=asociacion,
        motivo=motivo,
    )


def _exigir_motivo(motivo: str) -> str:
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Indicá el motivo.")
    return motivo


# ============================================================
# Membresías
# ============================================================

def _verificar_puede_resolver(membresia: Membresia, actor) -> None:
    if membresia.rol == Membresia.Rol.MODERADOR:
        if not es_gerente(actor):
            raise PermissionDenied("Sólo el gerente nombra moderadores.")
        if membresia.usuario_id == actor.pk:
            raise PermissionDenied("No podés aprobar tu propia membresía.")
    else:
        permisos.verificar_puede_moderar(actor, membresia.asociacion, sobre_usuario=membresia.usuario)


def _resolver(membresia: Membresia, actor, estado: str, motivo: str = "") -> None:
    membresia.estado = estado
    membresia.motivo = motivo
    membresia.resuelta_por = actor
    membresia.resuelta_el = timezone.now()
    membresia.save(update_fields=["estado", "motivo", "resuelta_por", "resuelta_el"])


@transaction.atomic
def aprobar_membresia(membresia: Membresia, actor) -> Membresia:
    _verificar_puede_resolver(membresia, actor)
    if membresia.estado == E.APROBADA:
        raise ValidationError("La membresía ya está aprobada.")
    accion = A.REACTIVAR if membresia.estado == E.SUSPENDIDA else A.APROBAR
    _resolver(membresia, actor, E.APROBADA)
    registrar(actor, accion, membresia, membresia.asociacion)
    return membresia


@transaction.atomic
def rechazar_membresia(membresia: Membresia, actor, motivo: str) -> Membresia:
    _verificar_puede_resolver(membresia, actor)
    if membresia.estado != E.PENDIENTE:
        raise ValidationError("Sólo se rechazan solicitudes pendientes.")
    motivo = _exigir_motivo(motivo)
    _resolver(membresia, actor, E.RECHAZADA, motivo)
    registrar(actor, A.RECHAZAR, membresia, membresia.asociacion, motivo)
    return membresia


@transaction.atomic
def suspender_membresia(membresia: Membresia, actor, motivo: str) -> Membresia:
    _verificar_puede_resolver(membresia, actor)
    if membresia.estado != E.APROBADA:
        raise ValidationError("Sólo se suspenden membresías aprobadas.")
    motivo = _exigir_motivo(motivo)
    _resolver(membresia, actor, E.SUSPENDIDA, motivo)
    registrar(actor, A.SUSPENDER, membresia, membresia.asociacion, motivo)
    return membresia


def _tiene_otro_vinculo_aprobado(usuario, excepto: Membresia) -> bool:
    otras = usuario.membresias.filter(estado=E.APROBADA).exclude(pk=excepto.pk).exists()
    accesos = hasattr(usuario, "accesos_cliente") and usuario.accesos_cliente.filter(estado="APROBADO").exists()
    return otras or accesos


@transaction.atomic
def marcar_spam(membresia: Membresia, actor) -> bool:
    """
    Rechaza la solicitud como spam. Si la persona no tiene ningún otro vínculo aprobado,
    además desactiva la cuenta. Devuelve True si se desactivó la cuenta.
    """
    _verificar_puede_resolver(membresia, actor)
    if membresia.estado != E.PENDIENTE:
        raise ValidationError("Sólo se marcan como spam solicitudes pendientes.")
    _resolver(membresia, actor, E.RECHAZADA, "Spam / registro falso")
    desactivada = False
    usuario = membresia.usuario
    if not _tiene_otro_vinculo_aprobado(usuario, membresia):
        usuario.is_active = False
        usuario.save(update_fields=["is_active"])
        desactivada = True
    registrar(actor, A.SPAM, membresia, membresia.asociacion,
              "Cuenta desactivada" if desactivada else "La cuenta sigue activa por otros vínculos")
    return desactivada


# ============================================================
# Perfil de piloto
# ============================================================

def _verificar_puede_moderar_perfil(perfil: PerfilPiloto, actor):
    asociaciones = list(perfil.asociaciones_aprobadas())
    if not asociaciones:
        raise ValidationError("El piloto todavía no tiene una membresía aprobada.")
    permisos.verificar_puede_moderar(actor, asociaciones, sobre_usuario=perfil.usuario)
    # Para el historial: la primera asociación que el actor modera.
    moderadas = set(permisos.asociaciones_moderadas(actor).values_list("pk", flat=True))
    return next(a for a in asociaciones if a.pk in moderadas)


@transaction.atomic
def aprobar_perfil(perfil: PerfilPiloto, actor) -> PerfilPiloto:
    asociacion = _verificar_puede_moderar_perfil(perfil, actor)
    if perfil.es_menor and not perfil.consentimiento_tutor:
        raise ValidationError("Es menor de edad: primero registrá el consentimiento del tutor.")
    perfil.aprobado = True
    perfil.aprobado_por = actor
    perfil.aprobado_el = timezone.now()
    perfil.cambio_tras_aprobacion = False
    perfil.save(update_fields=["aprobado", "aprobado_por", "aprobado_el", "cambio_tras_aprobacion"])
    registrar(actor, A.APROBAR, perfil, asociacion)
    return perfil


@transaction.atomic
def retirar_aprobacion_perfil(perfil: PerfilPiloto, actor, motivo: str) -> PerfilPiloto:
    asociacion = _verificar_puede_moderar_perfil(perfil, actor)
    motivo = _exigir_motivo(motivo)
    perfil.aprobado = False
    perfil.cambio_tras_aprobacion = False
    perfil.save(update_fields=["aprobado", "cambio_tras_aprobacion"])
    registrar(actor, A.RETIRAR, perfil, asociacion, motivo)
    return perfil


@transaction.atomic
def marcar_perfil_revisado(perfil: PerfilPiloto, actor) -> PerfilPiloto:
    """Los cambios posteriores a la aprobación se revisaron y quedan aceptados."""
    asociacion = _verificar_puede_moderar_perfil(perfil, actor)
    perfil.cambio_tras_aprobacion = False
    perfil.save(update_fields=["cambio_tras_aprobacion"])
    registrar(actor, A.REVISADO, perfil, asociacion)
    return perfil


@transaction.atomic
def registrar_consentimiento_tutor(perfil: PerfilPiloto, actor) -> PerfilPiloto:
    asociacion = _verificar_puede_moderar_perfil(perfil, actor)
    perfil.consentimiento_tutor = True
    perfil.consentimiento_tutor_por = actor
    perfil.consentimiento_tutor_el = timezone.now()
    perfil.save(update_fields=["consentimiento_tutor", "consentimiento_tutor_por", "consentimiento_tutor_el"])
    registrar(actor, A.CONSENTIMIENTO, perfil, asociacion)
    return perfil


@transaction.atomic
def cambiar_cuota(perfil: PerfilPiloto, actor, cuota_mb: int | None) -> PerfilPiloto:
    asociacion = _verificar_puede_moderar_perfil(perfil, actor)
    if cuota_mb is not None and cuota_mb < 0:
        raise ValidationError("La cuota no puede ser negativa.")
    anterior = perfil.cuota_efectiva_mb
    perfil.cuota_mb = cuota_mb
    perfil.save(update_fields=["cuota_mb"])
    registrar(actor, A.CUOTA, perfil, asociacion, f"{anterior} MB → {perfil.cuota_efectiva_mb} MB")
    return perfil


# ============================================================
# Accesos de cliente (los resuelve el personal del taller)
# ============================================================

EA = AccesoCliente.Estado


def _resolver_acceso(acceso: AccesoCliente, actor, estado: str, motivo: str = "") -> None:
    acceso.estado = estado
    acceso.motivo = motivo
    acceso.resuelto_por = actor
    acceso.resuelto_el = timezone.now()


@transaction.atomic
def aprobar_acceso(acceso: AccesoCliente, actor, cliente=None, rol: str | None = None) -> AccesoCliente:
    permisos.verificar_gestiona_accesos(actor)
    if acceso.estado == EA.APROBADO:
        raise ValidationError("El acceso ya está aprobado.")
    acceso.cliente = cliente or acceso.cliente
    if not acceso.cliente_id:
        raise ValidationError("Elegí a qué cliente corresponde antes de aprobar.")
    if rol:
        acceso.rol = rol
    acceso.full_clean()
    _resolver_acceso(acceso, actor, EA.APROBADO)
    acceso.save(update_fields=["cliente", "rol", "estado", "motivo", "resuelto_por", "resuelto_el"])
    registrar(actor, A.APROBAR, acceso)
    return acceso


@transaction.atomic
def rechazar_acceso(acceso: AccesoCliente, actor, motivo: str) -> AccesoCliente:
    permisos.verificar_gestiona_accesos(actor)
    if acceso.estado != EA.PENDIENTE:
        raise ValidationError("Sólo se rechazan solicitudes pendientes.")
    motivo = _exigir_motivo(motivo)
    _resolver_acceso(acceso, actor, EA.RECHAZADO, motivo)
    acceso.save(update_fields=["estado", "motivo", "resuelto_por", "resuelto_el"])
    registrar(actor, A.RECHAZAR, acceso, motivo=motivo)
    return acceso


@transaction.atomic
def revocar_acceso(acceso: AccesoCliente, actor, motivo: str) -> AccesoCliente:
    permisos.verificar_gestiona_accesos(actor)
    if acceso.estado != EA.APROBADO:
        raise ValidationError("Sólo se revocan accesos aprobados.")
    motivo = _exigir_motivo(motivo)
    _resolver_acceso(acceso, actor, EA.REVOCADO, motivo)
    acceso.save(update_fields=["estado", "motivo", "resuelto_por", "resuelto_el"])
    registrar(actor, A.REVOCAR, acceso, motivo=motivo)
    return acceso


# ============================================================
# Registro de cuentas
# ============================================================

@transaction.atomic
def registrar_cuenta(
    *,
    username: str,
    email: str,
    password: str,
    nombre: str,
    apellido: str,
    dni: str,
    fecha_nacimiento=None,
    asociacion: Asociacion | None = None,
    licencia: str = "",
    es_cliente: bool = False,
    nota_cliente: str = "",
):
    """
    Crea una cuenta del portal y las solicitudes que correspondan (todas PENDIENTES):
    - con `asociacion`: membresía de piloto + perfil (no público).
    - con `es_cliente`: acceso de cliente para que el taller lo identifique.
    Hasta que algo se apruebe, la cuenta sólo puede ver el estado de su solicitud.
    """
    Usuario = get_user_model()
    errores: dict[str, list[str]] = {}

    def error(campo, texto):
        errores.setdefault(campo, []).append(texto)

    username, email = (username or "").strip(), (email or "").strip().lower()
    nombre, apellido = (nombre or "").strip(), (apellido or "").strip()
    dni = Usuario.normalizar_dni(dni)

    if not asociacion and not es_cliente:
        error("__all__", "Elegí tu asociación, indicá que sos cliente del taller, o las dos cosas.")
    if not nombre:
        error("nombre", "Obligatorio.")
    if not apellido:
        error("apellido", "Obligatorio.")
    if not dni:
        error("dni", "Obligatorio.")
    elif Usuario.objects.filter(dni=dni).exists():
        error("dni", "Ya existe una cuenta con este documento.")
    try:
        validate_email(email)
        if Usuario.objects.filter(email__iexact=email).exists():
            error("email", "Ya existe una cuenta con este email.")
    except ValidationError:
        error("email", "Email inválido.")
    if asociacion is not None:
        if not asociacion.activa:
            error("asociacion", "Esa asociación no está disponible.")
        if not fecha_nacimiento:
            error("fecha_nacimiento", "Obligatoria para pilotos.")

    usuario = Usuario(
        username=username, email=email, first_name=nombre, last_name=apellido,
        dni=dni, tipo=Usuario.Tipo.PORTAL, is_staff=False,
    )
    try:
        validate_password(password, usuario)
    except ValidationError as e:
        errores.setdefault("password", []).extend(e.messages)
    try:
        usuario.full_clean(exclude=["password"])
    except ValidationError as e:
        for campo, mensajes in e.message_dict.items():
            if campo not in errores:  # no repetir lo ya avisado
                errores[campo] = mensajes
    if errores:
        raise ValidationError(errores)

    usuario.set_password(password)
    usuario.save()

    if asociacion is not None:
        Membresia.objects.create(usuario=usuario, asociacion=asociacion, rol=Membresia.Rol.PILOTO)
        PerfilPiloto.objects.create(
            usuario=usuario, nombre_publico=f"{nombre} {apellido}"[:80],
            fecha_nacimiento=fecha_nacimiento, licencia=(licencia or "").strip(),
        )
    if es_cliente:
        AccesoCliente.objects.create(
            usuario=usuario, nombre_declarado=f"{nombre} {apellido}", doc_declarado=dni,
            nota=(nota_cliente or "").strip(),
        )
    return usuario


def estado_de_cuenta(usuario) -> dict:
    """Resumen para el portal: qué tiene aprobado y qué está en revisión."""
    membresias = usuario.membresias.select_related("asociacion")
    accesos = usuario.accesos_cliente.select_related("cliente")
    return {
        "es_piloto": membresias.filter(rol=Membresia.Rol.PILOTO, estado=Membresia.Estado.APROBADA).exists(),
        "es_moderador": membresias.filter(rol=Membresia.Rol.MODERADOR, estado=Membresia.Estado.APROBADA).exists(),
        "es_cliente": accesos.filter(estado=EA.APROBADO).exists(),
        "pendientes": list(membresias.filter(estado=Membresia.Estado.PENDIENTE)) + list(accesos.filter(estado=EA.PENDIENTE)),
    }
