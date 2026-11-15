"""Lectura de números escritos a la argentina ('1.234.567,89')."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def parse_decimal_ar(raw: str | None, *, allow_empty: bool = False) -> Decimal | None:
    """'1.234,56' → Decimal('1234.56'). Vacío: None si allow_empty, si no error."""
    s = "" if raw is None else str(raw).strip()
    if not s:
        if allow_empty:
            return None
        raise ValidationError("Ingresá un número.")
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValidationError("Número inválido.")
