"""
Productos, stock y precios en el panel.
- Ver: todo el personal con view_producto (mecánico incluido, sin costos).
- Alta/edición: gestionar_productos (gerente, jefe). Precio: gestionar_precios (gerente).
- Stock: cada uno ve el de su sucursal (gerente elige); ajustes con change_stocksucursal.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.acceso import solo_personal
from core.models import Sucursal
from productos.models import ListaPrecio, MovimientoStock, PrecioProducto, Producto, StockSucursal, ajustar_stock
from taller.permisos import es_gerente

from .forms_gestion import AjusteStockForm, ListaPrecioForm, PrecioForm, ProductoForm, StockMinimoForm


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _puede(user, perm) -> bool:
    return user.is_superuser or user.has_perm(perm)


def _exigir(user, perm):
    if not _puede(user, perm):
        raise PermissionDenied


def _sucursal_de_trabajo(request):
    """La del usuario; el gerente puede elegir otra con ?sucursal=."""
    user = request.user
    if es_gerente(user):
        elegida = request.GET.get("sucursal")
        if elegida:
            return Sucursal.objects.filter(pk=elegida, activa=True).first()
        return user.sucursal or Sucursal.objects.filter(activa=True).first()
    return user.sucursal


def _pagina_form(request, titulo, form, volver, multipart=False):
    return render(request, "panel/form_pagina.html", {
        "titulo": titulo, "form": form, "volver": volver, "multipart": multipart,
    })


@solo_personal
def lista(request):
    user = request.user
    _exigir(user, "productos.view_producto")
    sucursal = _sucursal_de_trabajo(request)
    q = (request.GET.get("q") or "").strip()
    qs = Producto.objects.select_related("categoria")
    if request.GET.get("inactivos") != "1":
        qs = qs.filter(activo=True)
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(codigo_barras__icontains=q) | Q(sku__icontains=q) | Q(marca__icontains=q))
    tipo = request.GET.get("tipo") or ""
    if tipo in Producto.Tipo.values:
        qs = qs.filter(tipo=tipo)
    productos = list(qs.order_by("tipo", "nombre")[:300])
    stocks = {s.producto_id: s for s in StockSucursal.objects.filter(sucursal=sucursal, producto__in=productos)} if sucursal else {}
    filas = [{"p": p, "stock": stocks.get(p.pk)} for p in productos]
    return render(request, "panel/productos/lista.html", {
        "titulo": "Productos y servicios", "filas": filas, "q": q, "tipo": tipo, "sucursal": sucursal,
        "ver_costos": _puede(user, "productos.ver_costos"),
        "puede_crear": _puede(user, "productos.gestionar_productos"),
    })


@solo_personal
def detalle(request, pk):
    user = request.user
    _exigir(user, "productos.view_producto")
    p = get_object_or_404(Producto.objects.select_related("categoria"), pk=pk)
    stocks = StockSucursal.objects.filter(producto=p).select_related("sucursal")
    movimientos = MovimientoStock.objects.filter(producto=p).select_related("sucursal", "creado_por")
    if not es_gerente(user):
        stocks = stocks.filter(sucursal_id=user.sucursal_id)
        movimientos = movimientos.filter(sucursal_id=user.sucursal_id)
    return render(request, "panel/productos/detalle.html", {
        "titulo": p.nombre, "p": p, "stocks": stocks, "movimientos": movimientos[:30],
        "precios": PrecioProducto.objects.filter(producto=p).select_related("lista")[:20],
        "ver_costos": _puede(user, "productos.ver_costos"),
        "puede_editar": _puede(user, "productos.gestionar_productos"),
        "puede_stock": _puede(user, "productos.change_stocksucursal") and p.controla_stock,
        "ver_movimientos": _puede(user, "productos.view_movimientostock"),
    })


@solo_personal
def producto_form(request, pk=None):
    user = request.user
    _exigir(user, "productos.gestionar_productos")
    p = get_object_or_404(Producto, pk=pk) if pk else None
    form = ProductoForm(request.POST or None, request.FILES or None, instance=p,
                        puede_precio=_puede(user, "productos.gestionar_precios"))
    if request.method == "POST" and form.is_valid():
        try:
            p = form.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Producto guardado.")
            return redirect("productos:detalle", p.pk)
    volver = f"/panel/productos/{p.pk}/" if p else "/panel/productos/"
    return _pagina_form(request, "Editar producto" if p else "Nuevo producto", form, volver, multipart=True)


# ============================================================
# Stock
# ============================================================

@solo_personal
def stock(request):
    user = request.user
    _exigir(user, "productos.view_stocksucursal")
    sucursal = _sucursal_de_trabajo(request)
    qs = StockSucursal.objects.filter(sucursal=sucursal).select_related("producto") if sucursal else StockSucursal.objects.none()
    if request.GET.get("bajo") == "1":
        qs = qs.filter(stock_minimo__gt=0, stock__lt=F("stock_minimo"))
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(producto__nombre__icontains=q) | Q(producto__codigo_barras__icontains=q))
    return render(request, "panel/productos/stock.html", {
        "titulo": "Stock", "stocks": qs.order_by("producto__nombre")[:300], "sucursal": sucursal, "q": q,
        "bajo": request.GET.get("bajo") == "1", "sucursales": Sucursal.objects.filter(activa=True) if es_gerente(user) else [],
        "ver_costos": _puede(user, "productos.ver_costos"),
        "puede_ajustar": _puede(user, "productos.change_stocksucursal"),
    })


@solo_personal
def ajustar(request, pk):
    """Ajuste manual de stock de un producto en la sucursal de trabajo (queda como movimiento)."""
    user = request.user
    _exigir(user, "productos.change_stocksucursal")
    p = get_object_or_404(Producto, pk=pk, controla_stock=True)
    sucursal = _sucursal_de_trabajo(request)
    if sucursal is None:
        raise PermissionDenied("No tenés sucursal asignada.")
    actual = StockSucursal.objects.filter(producto=p, sucursal=sucursal).first()
    form = AjusteStockForm(request.POST or None)
    form_minimo = StockMinimoForm(request.POST or None, prefix="min",
                                  initial={"stock_minimo": actual.stock_minimo if actual else 0})
    if request.method == "POST":
        if "min-stock_minimo" in request.POST and form_minimo.is_valid():
            s, _ = StockSucursal.objects.get_or_create(producto=p, sucursal=sucursal)
            s.stock_minimo = form_minimo.cleaned_data["stock_minimo"]
            s.save(update_fields=["stock_minimo", "updated_at"])
            messages.success(request, "Stock mínimo actualizado.")
            return redirect("productos:detalle", p.pk)
        if "operacion" in request.POST and form.is_valid():
            d = form.cleaned_data
            delta = d["cantidad"] if d["operacion"] == "SUMAR" else -d["cantidad"]
            tipo = MovimientoStock.Tipo.AJUSTE_POSITIVO if delta > 0 else MovimientoStock.Tipo.AJUSTE_NEGATIVO
            try:
                ajustar_stock(sucursal=sucursal, producto=p, delta=Decimal(delta), tipo=tipo, usuario=user,
                              descripcion=d["motivo"])
            except ValidationError as e:
                form.add_error(None, _texto(e))
            else:
                messages.success(request, "Stock ajustado.")
                return redirect("productos:detalle", p.pk)
    return render(request, "panel/productos/ajustar.html", {
        "titulo": f"Stock de {p.nombre}", "p": p, "sucursal": sucursal, "actual": actual,
        "form": form, "form_minimo": form_minimo,
    })


# ============================================================
# Precios
# ============================================================

@solo_personal
def precios(request):
    _exigir(request.user, "productos.gestionar_precios")
    q = (request.GET.get("q") or "").strip()
    qs = PrecioProducto.objects.select_related("producto", "lista")
    if q:
        qs = qs.filter(producto__nombre__icontains=q)
    return render(request, "panel/productos/precios.html", {
        "titulo": "Precios", "precios": qs[:300], "q": q, "listas": ListaPrecio.objects.all(),
    })


@solo_personal
def precio_nuevo(request):
    _exigir(request.user, "productos.gestionar_precios")
    form = PrecioForm(request.POST or None, initial={"producto": request.GET.get("producto")})
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Precio cargado.")
            return redirect("productos:precios")
    return _pagina_form(request, "Nuevo precio", form, "/panel/productos/precios/")


@solo_personal
def lista_precio_nueva(request):
    _exigir(request.user, "productos.gestionar_precios")
    form = ListaPrecioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lista de precios creada.")
        return redirect("productos:precios")
    return _pagina_form(request, "Nueva lista de precios", form, "/panel/productos/precios/")
