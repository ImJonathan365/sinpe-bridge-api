"""
Parser de comprobantes SINPE en imagen (formato BCR - Banco de Costa Rica).
"""

import re
from datetime import datetime, timezone

from app.domain.payments.schemas import ParsedSinpeData

# Meses en español → número (para fechas tipo "02 de junio, 2026")
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

_BANCOS = ("BCR", "BAC", "BNCR", "BN", "Scotiabank", "Davivienda", "Popular", "Lafise", "Promerica")


def _parse_cr_amount(raw: str) -> float | None:
    """Convierte '2.500,00' (formato CR) a 2500.00."""
    raw = raw.strip()
    if "," in raw:
        # coma = decimales, punto = miles
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _find_amount(text: str) -> float | None:
    """
    Toma el MAYOR monto con símbolo ₡/¢ del comprobante.

    Un comprobante SINPE Móvil tiene tres montos: 'Monto debitado', 'Comisión'
    y 'Monto transferido'. En SINPE Móvil la comisión es ₡0, así que
    debitado == transferido == el mayor, y la comisión (0) es el menor.
    Quedarnos con el máximo es robusto al orden y a la AGRUPACIÓN de etiquetas
    que a veces hace el OCR (p. ej. "Comisión Monto transferido Motivo" seguido
    de los tres valores), donde anclar a la etiqueta agarraba el ₡0,00 por error.
    """
    amounts: list[float] = []
    for m in re.finditer(r"[₡¢]\s*([\d.,]+)", text):
        value = _parse_cr_amount(m.group(1))
        if value is not None:
            amounts.append(value)
    return max(amounts) if amounts else None


def _find_reference(text: str) -> str | None:
    """
    Número de referencia del comprobante.

    La referencia SINPE es un número largo (~22-26 dígitos) que arranca con el
    año (20XX, porque empieza con la fecha YYYYMMDD). La buscamos por ese patrón
    y NO por adyacencia a la etiqueta "Referencia", porque el OCR a veces separa
    la etiqueta de su valor (lo deja en otra línea, junto al número de cuenta).
    """
    # 1. Número largo que arranca con el año → patrón típico de referencia SINPE
    year_refs = re.findall(r"\b(20\d{18,30})\b", text)
    if year_refs:
        return max(year_refs, key=len)

    # 2. Respaldo: pegado a la etiqueta "Referencia" (layout limpio)
    m = re.search(r"Referencia[\s:#]*([0-9]{6,40})", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 3. Último recurso: el run de dígitos más largo y suficientemente largo
    runs = re.findall(r"\d{20,40}", text)
    if runs:
        return max(runs, key=len)
    return None


# Palabras que NO son parte del nombre (etiqueta y prefijos de cuenta).
_NAME_SKIP = {"AH", "CR", "CUENTA", "ORIGEN"}


def _find_name(text: str) -> str | None:
    """
    Nombre del pagador (bajo 'Cuenta origen'). Azure a veces parte la etiqueta
    ('Cuenta' en una línea, 'origen' en otra) y a veces deja el nombre en la
    misma línea de la cuenta. Por eso anclamos en 'Cuenta' y, en esa línea y las
    siguientes, descartamos tokens con dígitos (número de cuenta) y las palabras
    de la etiqueta, quedándonos con la secuencia de nombres en MAYÚSCULAS.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.search(r"cuenta", line, re.IGNORECASE):
            continue
        for candidate in lines[i:i + 4]:
            tokens = [
                t for t in candidate.split()
                if not any(c.isdigit() for c in t) and t.upper() not in _NAME_SKIP
            ]
            name = " ".join(tokens)
            if re.fullmatch(r"[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}", name):
                return name
        break
    return None


def _find_datetime(text: str) -> datetime | None:
    """Fecha tipo '02 de junio, 2026' + hora '10:21'."""
    date_m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+),?\s+(\d{4})", text, re.IGNORECASE)
    if not date_m:
        return None
    day = int(date_m.group(1))
    month = _MESES.get(date_m.group(2).lower())
    year = int(date_m.group(3))
    if not month:
        return None
    hour = minute = 0
    time_m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if time_m:
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


def _find_bank(text: str) -> str | None:
    upper = text.upper()
    for bank in _BANCOS:
        if bank.upper() in upper:
            return bank
    return None


def parse_receipt(text: str) -> ParsedSinpeData:
    """
    Extrae los campos estructurados de un comprobante SINPE en imagen (BCR).

    No se extrae `sender_phone`: en los comprobantes BCR el único teléfono
    presente es el "SINPE Móvil destino" (el comercio que recibe el pago),
    no el del remitente. Incluirlo aquí causaría que `rule_phone` compare
    el teléfono del comercio contra el `correlation_token` del cliente,
    lo cual nunca coincide.
    """
    return ParsedSinpeData(
        amount=_find_amount(text),
        sender_name=_find_name(text),
        sender_phone=None,
        reference=_find_reference(text),
        bank=_find_bank(text),
        transaction_at=_find_datetime(text),
    )