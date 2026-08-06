"""
Orquestador del flujo de comprobante en imagen.

Une todas las piezas, reutilizando el mismo motor que ya concilia los SMS:

    imagen → (guarda + hash) → Azure OCR → mapper → ParsedSinpeData
           → busca la orden pendiente → ReconciliationEngine.evaluate()
           → actualiza la orden → guarda SinpeImageReceipt → devuelve veredicto

El motor de reglas (ReconciliationEngine) no cambia: recibe el mismo
ParsedSinpeData sin importar si vino de un SMS o de un OCR.

El almacenamiento de la imagen es propio de este flujo (no usa el UploadService
basado en token), para mantener el pipeline OCR independiente.
"""

import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.correlation.repository import CorrelationSessionRepository
from app.domain.orders.repository import OrderRepository
from app.domain.payments.repository import SinpeMessageRepository
from app.domain.reconciliation.rules import ReconciliationEngine
from app.domain.uploads.repository import ImageReceiptRepository
from app.domain.uploads.schemas import ImageReconciliationResponse, ImageType
from app.infrastructure.ai.azure_ocr_client import AzureOcrError, get_ocr_client
from app.infrastructure.ai.mapper import map_ocr_to_parsed
from app.shared.enums import OrderStatus, ReconciliationResult

logger = logging.getLogger(__name__)

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


class SinpeImageAnalyzer:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._orders = OrderRepository(db)
        self._correlation_repo = CorrelationSessionRepository(db)
        self._messages = SinpeMessageRepository(db)
        self._receipts = ImageReceiptRepository(db)
        self._engine = ReconciliationEngine(ocr_min_confidence=settings.OCR_MIN_CONFIDENCE)
        self._ocr = get_ocr_client()
        self._storage_path = Path(settings.UPLOAD_STORAGE_PATH)

    async def _store_image(
        self, file_content: bytes, mime_type: str, file_hash: str
    ) -> tuple[str, str]:
        """
        Guarda la imagen en disco (best-effort) y devuelve (upload_id, relative_path).

        Si el guardado falla no bloquea el análisis: el texto OCR y la metadata
        igual quedan persistidos en la base. En ese caso relative_path es "".
        """
        upload_id = str(uuid.uuid4())
        ext = _EXT_BY_MIME.get(mime_type, ".bin")
        secure_filename = f"{upload_id}_{file_hash[:8]}{ext}"
        relative_path = ""
        try:
            now = datetime.utcnow()
            dir_path = self._storage_path / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
            dir_path.mkdir(parents=True, exist_ok=True)
            file_path = dir_path / secure_filename
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
            relative_path = str(file_path.relative_to(self._storage_path))
        except Exception as exc:  # noqa: BLE001 - el guardado es best-effort
            logger.warning("No se pudo guardar la imagen en disco: %s", exc)
        return upload_id, relative_path

    async def analyze(
        self,
        *,
        file_content: bytes,
        filename: str,
        mime_type: str,
        id_pos: str,
        correlation_token: str,
        device_id: str,
        correlation_id: str,
        message_id: str | None = None,
    ) -> ImageReconciliationResponse:

        # 1. Calcular el hash, guardar la imagen y obtener su tamaño
        file_hash = hashlib.sha256(file_content).hexdigest()
        file_size = len(file_content)
        upload_id, image_path = await self._store_image(file_content, mime_type, file_hash)

        # 2. Anti-duplicado: misma imagen subida dos veces
        if await self._receipts.hash_exists(file_hash):
            return ImageReconciliationResponse(
                upload_id=upload_id,
                reconciliation_result=ReconciliationResult.DUPLICATE.value,
                detail="Esta imagen ya fue procesada anteriormente.",
            )

        # 3. OCR con Azure
        try:
            ocr = await self._ocr.extract_text(file_content, mime_type)
            logger.info(
                "OCR ok (provider=%s, confidence=%.4f, upload_id=%s):\n%s",
                ocr.provider,
                ocr.confidence if ocr.confidence is not None else -1.0,
                upload_id,
                ocr.text,
            )
        except AzureOcrError as exc:
            logger.error("OCR falló: %s", exc)
            receipt = await self._receipts.create(
                id_pos=id_pos,
                upload_id=upload_id,
                file_hash=file_hash,
                image_url=image_path or None,
                image_storage_path=image_path or None,
                image_hash=file_hash,
                mime_type=mime_type or None,
                image_size_bytes=file_size or None,
                device_id=device_id,
                extracted_token=correlation_token,
                device_metadata={
                    "correlation_id": correlation_id,
                    "message_id": message_id,
                    "image_type": ImageType.RECEIPT_QR.value,
                },
                reconciliation_result=ReconciliationResult.UNDER_REVIEW.value,
                detail=f"OCR no disponible: {exc}",
            )
            return ImageReconciliationResponse(
                upload_id=upload_id,
                receipt_id=str(receipt.id),
                reconciliation_result=ReconciliationResult.UNDER_REVIEW.value,
                detail=f"No se pudo leer la imagen (OCR): {exc}",
            )

        # 4. Mapear el texto OCR a campos estructurados
        parsed = map_ocr_to_parsed(ocr)

        # 5. Buscar la orden correspondiente a este pago por id_pos + correlation_token
        order = await self._orders.get_by_pos_and_token(id_pos, correlation_token)

        # Base de la respuesta con todo lo extraído (se completa con el veredicto)
        base = dict(
            upload_id=upload_id,
            ocr_confidence=ocr.confidence,
            amount=parsed.amount,
            sender_name=parsed.sender_name,
            sender_phone=parsed.sender_phone,
            reference=parsed.reference,
            bank=parsed.bank,
            transaction_at=parsed.transaction_at,
        )

        if order is None:
            receipt = await self._persist(
                id_pos, upload_id, file_hash, ocr, parsed,
                ReconciliationResult.NO_ORDER_FOUND,
                "No se encontró ninguna orden para el id_pos y correlation_token enviados.",
                None,
                image_path=image_path,
                image_size=file_size,
                mime_type=mime_type,
                device_id=device_id,
                correlation_id=correlation_id,
                message_id=message_id,
                extracted_token=correlation_token,
            )
            return ImageReconciliationResponse(
                **base,
                receipt_id=str(receipt.id),
                reconciliation_result=ReconciliationResult.NO_ORDER_FOUND.value,
                detail="No se encontró ninguna orden para el id_pos y correlation_token enviados.",
            )

        # 5b. Buscar o crear la sesión de correlación (asocia esta imagen a la orden)
        session = await self._correlation_repo.get_by_token(id_pos, correlation_token)
        if not session:
            session = await self._correlation_repo.create(
                order_id=order.id,
                token=correlation_token,
                expires_at=order.expires_at,
            )

        # 6. ¿La referencia ya se usó? (chequeo cruzado: SMS + imágenes)
        reference_used = False
        if parsed.reference:
            reference_used = (
                await self._messages.reference_exists(parsed.reference)
                or await self._receipts.reference_exists(parsed.reference)
            )

        # 7. Ejecutar el motor de reglas (duras + score 0-100 sobre las blandas)
        result, detail, score = self._engine.evaluate(
            order, parsed, reference_used, ocr_confidence=ocr.confidence
        )

        # 9. Actualizar el estado de la orden según el resultado
        new_status: OrderStatus | None = None
        if result == ReconciliationResult.APPROVED:
            new_status = OrderStatus.CONFIRMED
        elif result == ReconciliationResult.UNDER_REVIEW:
            new_status = OrderStatus.REVIEW
        elif result == ReconciliationResult.EXPIRED:
            new_status = OrderStatus.EXPIRED
        if new_status:
            await self._orders.update_status(order.id, new_status)

        # 10. Persistir el comprobante con su veredicto
        linked_order = order.id if result != ReconciliationResult.DUPLICATE else None
        receipt = await self._persist(
            id_pos, upload_id, file_hash, ocr, parsed,
            result, detail, linked_order,
            image_path=image_path,
            image_size=file_size,
            mime_type=mime_type,
            device_id=device_id,
            correlation_id=correlation_id,
            message_id=message_id,
            correlation_session_id=session.id,
            extracted_token=correlation_token,
        )

        return ImageReconciliationResponse(
            **base,
            receipt_id=str(receipt.id),
            reconciliation_result=result.value,
            order_number=order.order_number,
            detail=detail,
        )

    async def _persist(
        self,
        id_pos,
        upload_id,
        file_hash,
        ocr,
        parsed,
        result,
        detail,
        order_id,
        *,
        image_path: str = "",
        image_size: int = 0,
        mime_type: str = "",
        device_id: str | None = None,
        correlation_id: str | None = None,
        message_id: str | None = None,
        correlation_session_id=None,
        extracted_token: str | None = None,
    ):
        return await self._receipts.create(
            id_pos=id_pos,
            upload_id=upload_id,
            file_hash=file_hash,
            ocr_provider=ocr.provider,
            ocr_text=ocr.text,
            ocr_confidence=ocr.confidence,
            amount=parsed.amount,
            sender_name=parsed.sender_name,
            sender_phone=parsed.sender_phone,
            reference=parsed.reference,
            bank=parsed.bank,
            transaction_at=parsed.transaction_at,
            reconciliation_result=result.value,
            detail=detail,
            purchase_order_id=order_id,
            correlation_session_id=correlation_session_id,
            image_url=image_path or None,
            image_storage_path=image_path or None,
            image_hash=file_hash,
            mime_type=mime_type or None,
            image_size_bytes=image_size or None,
            device_id=device_id,
            extracted_token=extracted_token,
            device_metadata={
                "correlation_id": correlation_id,
                "message_id": message_id,
                "image_type": ImageType.RECEIPT_QR.value,
            },
        )