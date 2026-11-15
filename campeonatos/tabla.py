"""
Tabla de posiciones de una categoría, calculada en el momento.

- Suma los resultados PROVISORIOS y VALIDADOS (los observados y anulados no suman).
- Desempate: más victorias en finales, después más segundos puestos, después terceros, etc.
- Devuelve también si la tabla todavía incluye resultados sin validar (provisoria).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from .models import Categoria, Inscripcion, Resultado, TipoCarrera


@dataclass
class FilaTabla:
    inscripcion: Inscripcion
    puntos: Decimal = Decimal("0")
    carreras: int = 0
    llegadas: Counter = field(default_factory=Counter)  # posición en finales -> cantidad
    provisorios: int = 0
    posicion: int = 0

    @property
    def numero(self) -> str:
        return self.inscripcion.numero

    @property
    def nombre(self) -> str:
        return self.inscripcion.nombre_mostrado

    @property
    def perfil_publico_slug(self) -> str | None:
        """Sólo si el perfil está aprobado y es público se puede enlazar."""
        piloto = self.inscripcion.piloto
        return piloto.slug if piloto.visible_en_web else None

    @property
    def victorias(self) -> int:
        return self.llegadas[1]

    @property
    def podios(self) -> int:
        return self.llegadas[1] + self.llegadas[2] + self.llegadas[3]


def tabla_posiciones(categoria: Categoria) -> tuple[list[FilaTabla], bool]:
    filas: dict[int, FilaTabla] = {}
    for insc in categoria.inscripciones.select_related("piloto__usuario"):
        if insc.estado == Inscripcion.Estado.ACTIVA:
            filas[insc.pk] = FilaTabla(insc)

    resultados = Resultado.objects.filter(
        inscripcion__categoria=categoria, estado__in=Resultado.ESTADOS_QUE_SUMAN,
    ).select_related("carrera", "inscripcion__piloto__usuario")
    for r in resultados:
        fila = filas.setdefault(r.inscripcion_id, FilaTabla(r.inscripcion))  # incluye bajas que ya sumaron
        fila.puntos += r.puntos
        fila.carreras += 1
        if r.estado == Resultado.Estado.PROVISORIO:
            fila.provisorios += 1
        if r.carrera.tipo == TipoCarrera.FINAL and r.condicion == Resultado.Condicion.FINALIZO and r.posicion:
            fila.llegadas[r.posicion] += 1

    peor = max((max(f.llegadas, default=0) for f in filas.values()), default=0)

    def clave(f: FilaTabla):
        return (-f.puntos, *[-f.llegadas[p] for p in range(1, peor + 1)], f.nombre.lower())

    ordenadas = sorted(filas.values(), key=clave)
    for i, f in enumerate(ordenadas, start=1):
        f.posicion = i
    return ordenadas, any(f.provisorios for f in ordenadas)
