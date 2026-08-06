"""
Schemas para sinpe_raw_messages.
La app móvil usa estos contratos para comunicarse con la API.
El formato coincide exactamente con cuerpo-msj.txt.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


#Sub-schemas del envelope que manda la app móvil ─
class SinpeEnvelope(BaseModel):
    content_hash: str
    correlation_id: str
    created_at: int          # unix timestamp
    device_hash: str
    message_id: str          # UUID único del mensaje
    retry_count: int = 0
    signature: str
    source: str
    status: str
    version: str = "1.0"


class SinpeDebug(BaseModel):
    format: str | None = None
    pdu: str | None = None


class SinpeDevice(BaseModel):
    sim_slot: int | None = None
    subscription_id: int | None = None


class SinpeMetadata(BaseModel):
    protocol_id: int | None = None
    service_center: str | None = None
    status: int | None = None


class SinpeMultipart(BaseModel):
    ref: int = 0
    seq: int = 1
    total: int = 1


class SinpePayload(BaseModel):
    body: str                          # Texto crudo del SMS
    debug: SinpeDebug | None = None
    device: SinpeDevice | None = None
    metadata: SinpeMetadata | None = None
    multipart: SinpeMultipart | None = None
    sender: str | None = None          # Número del banco
    timestamp: int | None = None       # Unix timestamp del SMS


#  Request principal 

class SinpeMessageCreate(BaseModel):
    """
    Payload completo que manda la app móvil.
    Estructura idéntica a cuerpo-msj.txt más el id_pos.
    """
    id_pos: str = Field(min_length=1, max_length=64)
    correlation_token: str = Field(min_length=1, max_length=8)
    envelope: SinpeEnvelope
    payload: SinpePayload


#  Response 

class SinpeMessageResponse(BaseModel):
    """Lo que la API devuelve a la app móvil tras recibir el mensaje."""
    id: uuid.UUID
    message_id: uuid.UUID
    id_pos: str
    body: str
    sender: str | None
    message_timestamp: datetime | None
    processed: bool
    received_at: datetime
    purchase_order_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# CONCILIACIÓN 

class ParsedSinpeData(BaseModel):
    """
    Datos estructurados extraídos de un comprobante SINPE.
    """
    amount: float | None = None              # Monto
    sender_name: str | None = None           # Nombre 
    sender_phone: str | None = None          # Teléfono de quien paga 
    reference: str | None = None             # Número de referencia
    bank: str | None = None                  # Banco 
    transaction_at: datetime | None = None   # Fecha/hora de la transacción


# El payload que recibe el motor de conciliación es idéntico al que manda la app móvil, así que reutilizamos el mismo contrato en lugar de duplicarlo.
SinpeMessageIncoming = SinpeMessageCreate


class SinpeIncomingResponse(BaseModel):
    """Resultado de procesar y conciliar un mensaje SINPE entrante."""
    message_id: uuid.UUID
    processed: bool
    reconciliation_result: str | None = None   # valor ReconciliationResult
    order_number: str | None = None
    detail: str | None = None
