from datetime import datetime, timezone

from app.domain.payments.schemas import ParsedSinpeData
from app.infrastructure.db.models import PurchaseOrder as PurchaseOrderModel
from app.shared.constants import (
    APPROVAL_SCORE_THRESHOLD,
    MAX_AMOUNT_DIFF,
    PAYMENT_EXPIRY_MINUTES,
    SCORE_BASE_HARD_RULES,
    SCORE_OCR_CONFIDENCE,
    SCORE_SENDER_NAME_PRESENT,
)
from app.shared.enums import ReconciliationResult


# Funciones individuales de cada regla


def rule_amount(
    order: PurchaseOrderModel, parsed: ParsedSinpeData
) -> tuple[bool, str]:
    """El monto del comprobante debe coincidir exactamente con el monto de la orden."""
    if parsed.amount is None:
        return False, "No se pudo extraer el monto del comprobante"
    diff = abs(float(order.amount) - parsed.amount)
    if diff > MAX_AMOUNT_DIFF:
        return (
            False,
            f"Monto no coincide: orden={order.amount}, comprobante={parsed.amount}",
        )
    return True, "El monto coincide"


def rule_time_window(
    order: PurchaseOrderModel, parsed: ParsedSinpeData
) -> tuple[bool, str]:
    """El timestamp del comprobante debe estar dentro de la ventana de tiempo válida."""
    if parsed.transaction_at is None:
        # Sin timestamp no se puede verificar, se deja pasar (regla blanda)
        return True, "Verificación de tiempo omitida (el comprobante no tiene fecha/hora)"

    reference_time = order.ordered_at.replace(tzinfo=timezone.utc) if order.ordered_at.tzinfo is None else order.ordered_at

    # Usar expires_at si está definido, sino calcularlo desde ordered_at
    if order.expires_at:
        deadline = order.expires_at.replace(tzinfo=timezone.utc) if order.expires_at.tzinfo is None else order.expires_at
    else:
        from datetime import timedelta
        deadline = reference_time + timedelta(minutes=PAYMENT_EXPIRY_MINUTES)

    tx_time = parsed.transaction_at
    if tx_time < reference_time:
        return False, "La fecha/hora del comprobante es anterior a la creación de la orden"
    if tx_time > deadline:
        return (
            False,
            f"El comprobante está fuera de la ventana de {PAYMENT_EXPIRY_MINUTES} minutos",
        )
    return True, "El comprobante está dentro de la ventana de tiempo válida"


def rule_reference_unique(reference: str | None, already_used: bool) -> tuple[bool, str]:
    """El número de referencia SINPE no debe haber sido usado antes."""
    if reference is None:
        return False, "No se pudo extraer la referencia del comprobante"
    if already_used:
        return False, f"La referencia {reference} ya fue usada (pago duplicado)"
    return True, "La referencia es única"


def rule_ocr_confidence(ocr_confidence: float | None, min_confidence: float) -> tuple[bool, str]:
    """La confianza del OCR debe ser razonablemente alta."""
    if ocr_confidence is None:
        return False, "El OCR no devolvió un valor de confianza"
    if ocr_confidence < min_confidence:
        return False, f"Confianza de OCR baja ({ocr_confidence:.2f} < {min_confidence})"
    return True, f"Confianza de OCR aceptable ({ocr_confidence:.2f})"


def rule_sender_name_present(parsed: ParsedSinpeData) -> tuple[bool, str]:
    """El comprobante debe contener un nombre de remitente legible."""
    if parsed.sender_name:
        return True, f"Nombre del remitente extraído: {parsed.sender_name}"
    return False, "No se pudo extraer el nombre del remitente del comprobante"


# Motor de conciliación


class ReconciliationEngine:
    """
    Ejecuta las reglas duras (monto, referencia, ventana de tiempo) contra una
    orden y los datos extraídos del comprobante en imagen. Si todas pasan,
    calcula un puntaje de 0 a 100 con las reglas blandas (confianza del OCR,
    presencia de nombre del remitente) para decidir entre APPROVED y
    UNDER_REVIEW.
    """

    def __init__(self, ocr_min_confidence: float) -> None:
        self._ocr_min_confidence = ocr_min_confidence

    def evaluate(
        self,
        order: PurchaseOrderModel,
        parsed: ParsedSinpeData,
        reference_already_used: bool = False,
        ocr_confidence: float | None = None,
    ) -> tuple[ReconciliationResult, str, int]:
        """
        Devuelve (resultado, detalle, score). El score es 0 si el flujo corta
        por una regla dura (REJECTED / DUPLICATE / EXPIRED).
        """

        # REGLA DURA: referencia única
        passed, reason = rule_reference_unique(parsed.reference, reference_already_used)
        if not passed:
            result = (
                ReconciliationResult.DUPLICATE
                if reference_already_used
                else ReconciliationResult.REJECTED
            )
            return result, reason, 0

        # REGLA DURA: monto
        passed, reason = rule_amount(order, parsed)
        if not passed:
            return ReconciliationResult.REJECTED, reason, 0

        # REGLA DURA: ventana de tiempo
        passed, reason = rule_time_window(order, parsed)
        if not passed:
            return ReconciliationResult.EXPIRED, reason, 0

        # Reglas duras superadas: puntaje base
        score = SCORE_BASE_HARD_RULES
        reasons = [
            "El monto coincide",
            "La referencia es única",
            "El comprobante está dentro de la ventana de tiempo válida",
        ]

        # REGLA BLANDA: confianza del OCR
        passed, reason = rule_ocr_confidence(ocr_confidence, self._ocr_min_confidence)
        reasons.append(reason)
        if passed:
            score += SCORE_OCR_CONFIDENCE

        # REGLA BLANDA: nombre del remitente presente
        passed, reason = rule_sender_name_present(parsed)
        reasons.append(reason)
        if passed:
            score += SCORE_SENDER_NAME_PRESENT

        detail = f"Puntaje: {score}/100. " + "; ".join(reasons)

        if score >= APPROVAL_SCORE_THRESHOLD:
            return ReconciliationResult.APPROVED, detail, score

        return ReconciliationResult.UNDER_REVIEW, detail, score