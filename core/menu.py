"""
Menús del panel y del portal.

Cada ítem dice a qué URL va y quién lo ve. Un ítem cuya URL todavía no existe (pantallas que
se agregan en partes siguientes) simplemente no aparece, así el menú crece solo a medida que
se construye el sistema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.urls import NoReverseMatch, reverse


@dataclass
class Item:
    titulo: str
    url_name: str
    icono: str
    desc: str = ""
    puede: Callable | None = None   # función usuario -> bool; None = todos los del área
    rapido: bool = False            # aparece en la barra inferior del celular
    corto: str = ""                 # texto corto para la barra inferior


@dataclass
class Seccion:
    titulo: str
    icono: str
    items: list[Item] = field(default_factory=list)


def _perm(*permisos: str) -> Callable:
    """Alcanza con tener uno de los permisos."""
    return lambda u: u.is_superuser or any(u.has_perm(p) for p in permisos)


def _es_mecanico(u) -> bool:
    from taller.permisos import es_solo_mecanico

    return es_solo_mecanico(u)


MENU_PANEL = [
    Seccion("Taller", "bi-wrench-adjustable", [
        Item("Mis órdenes", "taller:mis_ordenes", "bi-person-workspace", "Trabajos asignados a mí",
             puede=_es_mecanico, rapido=True, corto="Mis OT"),
        Item("Órdenes de trabajo", "taller:ordenes", "bi-clipboard-check", "Presupuestos y trabajos",
             puede=_perm("taller.cambiar_estado_orden"), rapido=True, corto="Órdenes"),
        Item("Turnos", "taller:turnos", "bi-calendar-week", "Agenda de la sucursal",
             puede=_perm("taller.view_turno"), rapido=True),
        Item("Vehículos", "taller:vehiculos", "bi-car-front", "Fichas del taller",
             puede=_perm("taller.view_vehiculo")),
    ]),
    Seccion("Caja y ventas", "bi-cash-coin", [
        Item("Caja", "core:caja", "bi-cash-stack", "Abrir, mover y cerrar",
             puede=_perm("core.abrir_caja", "core.movimientos_caja")),
        Item("Por cobrar", "ventas:por_cobrar", "bi-receipt", "Ventas de órdenes entregadas",
             puede=_perm("ventas.finalizar_venta"), rapido=True, corto="Cobrar"),
        Item("Venta de mostrador", "ventas:mostrador", "bi-bag-plus", "Repuestos sin orden",
             puede=_perm("ventas.crear_venta")),
        Item("Listado de ventas", "ventas:listado", "bi-journal-text", "Buscar y anular",
             puede=_perm("ventas.ver_ventas")),
    ]),
    Seccion("Stock y compras", "bi-box-seam", [
        Item("Productos y servicios", "productos:lista", "bi-box-seam", "Repuestos y mano de obra",
             puede=_perm("productos.view_producto")),
        Item("Stock", "productos:stock", "bi-boxes", "Por sucursal",
             puede=_perm("productos.view_stocksucursal")),
        Item("Precios", "productos:precios", "bi-tags", "Listas y promociones",
             puede=_perm("productos.gestionar_precios")),
        Item("Compras", "compras:lista", "bi-truck", "Facturas de proveedores",
             puede=_perm("compras.registrar_compras")),
        Item("Proveedores", "compras:proveedores", "bi-building", "",
             puede=_perm("compras.gestionar_proveedores")),
    ]),
    Seccion("Clientes", "bi-people", [
        Item("Clientes", "clientes:lista", "bi-people", "Datos y cuenta corriente",
             puede=_perm("clientes.ver_clientes")),
        Item("Accesos al portal", "admin:portal_accesocliente_changelist", "bi-person-check",
             "Clientes que piden ver su taller", puede=_perm("portal.gestionar_accesos_cliente")),
    ]),
    Seccion("Sistema", "bi-gear", [
        Item("Mi PIN", "core:pin", "bi-key", "Para acciones de caja"),
        Item("Administrador", "admin:index", "bi-gear", "Usuarios, empresa, sucursales",
             puede=lambda u: u.is_staff),
    ]),
]


def _menu_portal(user) -> list[Seccion]:
    from portal.servicios import estado_de_cuenta

    estado = estado_de_cuenta(user)
    secciones = [
        Seccion("Mi cuenta", "bi-person", [
            Item("Mi perfil", "portal:perfil", "bi-person-badge", "Biografía, foto y palmarés",
                 puede=lambda u: estado["es_piloto"], rapido=True, corto="Perfil"),
            Item("Mis autos", "portal:autos", "bi-car-front-fill", "Presentación, fotos y setups",
                 puede=lambda u: estado["es_piloto"], rapido=True, corto="Autos"),
            Item("Mis archivos", "portal:archivos", "bi-folder2", "Fotos, setups y telemetría",
                 puede=lambda u: estado["es_piloto"]),
        ]),
        Seccion("Campeonatos", "bi-trophy", [
            Item("Mis campeonatos", "campeonatos_portal:inicio", "bi-trophy", "Inscripción, resultados y tabla",
                 puede=lambda u: estado["es_piloto"], rapido=True, corto="Campeonato"),
        ]),
        Seccion("Mi taller", "bi-wrench", [
            Item("Mis vehículos y órdenes", "portal:mi_taller", "bi-clipboard-check", "Trabajos, presupuestos e historial",
                 puede=lambda u: estado["es_cliente"], rapido=True, corto="Taller"),
            Item("Turnos", "portal:turnos", "bi-calendar-plus", "Pedir y ver turnos",
                 puede=lambda u: estado["es_cliente"]),
        ]),
        Seccion("Moderación", "bi-shield-check", [
            Item("Pendientes", "portal:moderacion", "bi-inbox", "Lo que espera aprobación",
                 puede=lambda u: estado["es_moderador"]),
            Item("Pilotos", "portal:moderacion_miembros", "bi-people", "Miembros, cuota y suspensiones",
                 puede=lambda u: estado["es_moderador"]),
            Item("Campeonatos", "campeonatos_mod:lista", "bi-trophy", "Fechas, puntos y resultados",
                 puede=lambda u: estado["es_moderador"]),
            Item("Historial", "portal:moderacion_historial", "bi-clock-history", "Quién aprobó qué",
                 puede=lambda u: estado["es_moderador"]),
        ]),
    ]
    return secciones


def _resolver(secciones: list[Seccion], user) -> list[dict]:
    resultado = []
    for seccion in secciones:
        items = []
        for item in seccion.items:
            if item.puede is not None and not item.puede(user):
                continue
            try:
                url = reverse(item.url_name)
            except NoReverseMatch:
                continue  # pantalla todavía no construida
            items.append({**item.__dict__, "url": url})
        if items:
            resultado.append({"titulo": seccion.titulo, "icono": seccion.icono, "items": items})
    return resultado


def construir_menu(user, area: str) -> dict:
    if area == "portal":
        secciones, inicio = _resolver(_menu_portal(user), user), reverse("portal:inicio")
    else:
        secciones, inicio = _resolver(MENU_PANEL, user), reverse("panel:inicio")
    rapidos = [i for s in secciones for i in s["items"] if i["rapido"]][:3]
    return {"area": area, "inicio": inicio, "secciones": secciones, "rapidos": rapidos}
