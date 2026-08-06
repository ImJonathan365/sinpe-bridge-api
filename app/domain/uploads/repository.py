"""Acceso a datos para sinpe_image_receipts (comprobantes en imagen)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import SinpeImageReceipt


class UploadRepository:
    """Persistencia del flujo de subida basado en token + sesión de correlación."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_receipt(
        self,
        correlation_session_id,
        id_pos: str,
        image_url: str,
        image_storage_path: str,
        image_hash: str,
        file_hash: str,
        mime_type: str,
        image_size_bytes: int,
        device_id: str,
        extracted_token: str,
        upload_id: str,
        device_metadata: dict | None = None,
    ) -> SinpeImageReceipt:
        receipt = SinpeImageReceipt(
            upload_id=upload_id,
            correlation_session_id=correlation_session_id,
            id_pos=id_pos,
            image_url=image_url,
            image_storage_path=image_storage_path,
            image_hash=image_hash,
            file_hash=file_hash,
            mime_type=mime_type,
            image_size_bytes=image_size_bytes,
            device_id=device_id,
            extracted_token=extracted_token,
            device_metadata=device_metadata or {},
        )
        self._db.add(receipt)
        await self._db.commit()
        await self._db.refresh(receipt)
        return receipt


class ImageReceiptRepository:
    """Persistencia del flujo OCR + conciliación."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, **fields) -> SinpeImageReceipt:
        receipt = SinpeImageReceipt(**fields)
        self._db.add(receipt)
        await self._db.commit()
        await self._db.refresh(receipt)
        return receipt

    async def get_by_id(self, receipt_id: uuid.UUID) -> SinpeImageReceipt | None:
        result = await self._db.execute(
            select(SinpeImageReceipt).where(SinpeImageReceipt.id == receipt_id)
        )
        return result.scalar_one_or_none()

    async def hash_exists(self, file_hash: str) -> bool:
        """True si esa misma imagen (por hash) ya fue procesada antes."""
        result = await self._db.execute(
            select(SinpeImageReceipt.id).where(
                SinpeImageReceipt.file_hash == file_hash
            )
        )
        return result.first() is not None

    async def reference_exists(self, reference: str) -> bool:
        """True si esa referencia SINPE ya fue usada por otro comprobante en imagen."""
        result = await self._db.execute(
            select(SinpeImageReceipt.id).where(
                SinpeImageReceipt.reference == reference
            )
        )
        return result.first() is not None
