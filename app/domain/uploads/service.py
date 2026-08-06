import logging
import hashlib
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
import uuid
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.domain.correlation.repository import CorrelationSessionRepository
from app.domain.orders.repository import OrderRepository
from app.domain.uploads.repository import UploadRepository
from app.domain.uploads.schemas import ImageType, UploadResponse

logger = logging.getLogger(__name__)


class UploadService:
    
    ALLOWED_MIME_TYPES = {
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
        "image/webp": [".webp"],
        "application/pdf": [".pdf"],
    }
    
    def __init__(self, db: AsyncSession):
        self._db = db
        self._order_repo = OrderRepository(db)
        self._correlation_repo = CorrelationSessionRepository(db)
        self._upload_repo = UploadRepository(db)
        self.max_file_size = settings.MAX_UPLOAD_SIZE
        self.storage_path = Path(settings.UPLOAD_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str,
        image_type: ImageType,
        id_pos: str,
        correlation_token: str,
        device_id: str,
        correlation_id: str,
        message_id: Optional[str] = None,
    ) -> UploadResponse:
        file_size = len(file_content)
        if file_size > self.max_file_size:
            raise ValueError(
                f"File too large: {file_size} > {self.max_file_size} bytes"
            )
        
        if mime_type not in self.ALLOWED_MIME_TYPES:
            raise ValueError(f"MIME type not allowed: {mime_type}")
        
        _, ext = os.path.splitext(filename)
        allowed_exts = self.ALLOWED_MIME_TYPES[mime_type]
        if ext.lower() not in allowed_exts:
            raise ValueError(
                f"File extension {ext} not allowed for {mime_type}"
            )

        upload_id = str(uuid.uuid4())
        file_hash = hashlib.sha256(file_content).hexdigest()
        secure_filename = f"{upload_id}_{file_hash[:8]}{ext}"
        
        now = datetime.utcnow()
        device_hash = hashlib.sha256(device_id.encode()).hexdigest()[:16]
        
        dir_path = (
            self.storage_path
            / str(now.year)
            / f"{now.month:02d}"
            / f"{now.day:02d}"
            / device_hash
        )
        dir_path.mkdir(parents=True, exist_ok=True)
        
        file_path = dir_path / secure_filename
        
        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
            logger.info(
                f"File uploaded: {secure_filename}, size={file_size}, "
                f"hash={file_hash}, device_hash={device_hash}"
            )
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            raise ValueError(f"Storage error: {e}")

        order = await self._order_repo.get_by_pos_and_token(id_pos, correlation_token)
        if not order:
            raise ValueError("No se encontró una orden para el id_pos y correlation_token enviados")

        session = await self._correlation_repo.get_by_token(id_pos, correlation_token)
        if not session:
            session = await self._correlation_repo.create(
                order_id=order.id,
                token=correlation_token,
                expires_at=order.expires_at,
            )

        receipt = await self._upload_repo.create_receipt(
            upload_id=upload_id,
            correlation_session_id=session.id,
            id_pos=id_pos,
            image_url=str(file_path.relative_to(self.storage_path)),
            image_storage_path=str(file_path.relative_to(self.storage_path)),
            image_hash=file_hash,
            file_hash=file_hash,
            mime_type=mime_type,
            image_size_bytes=file_size,
            device_id=device_id,
            extracted_token=correlation_token,
            device_metadata={
                "correlation_id": correlation_id,
                "message_id": message_id,
                "image_type": image_type.value,
            },
        )
                
        return UploadResponse(
            upload_id=str(receipt.id),
            file_path=str(file_path.relative_to(self.storage_path)),
            file_size=file_size,
            mime_type=mime_type,
            image_type=image_type,
            correlation_id=correlation_id,
            message_id=message_id,
            created_at=datetime.utcnow(),
        )
    
    async def get_file_path(self, upload_id: str) -> Optional[Path]:
        for root, dirs, files in os.walk(self.storage_path):
            for file in files:
                if file.startswith(upload_id):
                    return Path(root) / file
        return None
    
    async def delete_file(self, upload_id: str) -> bool:
        file_path = await self.get_file_path(upload_id)
        if file_path and file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"File deleted: {upload_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete file: {e}")
                return False
        return False
    
    def compute_file_hash(self, file_content: bytes) -> str:
        return hashlib.sha256(file_content).hexdigest()


