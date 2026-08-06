# Minutos máximos entre la orden y el pago para considerarlo válido
PAYMENT_WINDOW_MINUTES = 15

# Minutos de vigencia del pago contados desde la creación de la orden.
PAYMENT_EXPIRY_MINUTES = 15

# Diferencia máxima (en colones) tolerada entre el monto de la orden y el del pago.
MAX_AMOUNT_DIFF = 0.0

# Umbral de similitud (0.0 a 1.0) para considerar que dos nombres coinciden.
NAME_SIMILARITY_THRESHOLD = 0.6

# --- Sistema de puntaje de conciliación (0-100) ---
# Reglas duras (monto, referencia, ventana de tiempo) cortan el flujo
# inmediatamente si fallan (REJECTED / DUPLICATE / EXPIRED) y no usan estos
# pesos. Los pesos abajo se aplican a las reglas "blandas" que sí pasaron las
# reglas duras, y determinan si el resultado es APPROVED o UNDER_REVIEW.

# Puntaje base otorgado cuando las 3 reglas duras (monto, referencia, ventana
# de tiempo) pasaron correctamente.
SCORE_BASE_HARD_RULES = 70

# Puntos adicionales si la confianza del OCR es >= OCR_MIN_CONFIDENCE.
SCORE_OCR_CONFIDENCE = 20

# Puntos adicionales si se pudo extraer un nombre de remitente del comprobante
# (sender_name no es None). No se compara contra nada (la orden no tiene
# nombre del cliente), pero da indicio de que el comprobante es legible/real.
SCORE_SENDER_NAME_PRESENT = 10

# Umbral de aprobación automática.
APPROVAL_SCORE_THRESHOLD = 80