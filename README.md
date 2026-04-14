# SINPE Bridge API

La SINPE Bridge API es un servicio backend diseñado para validar pagos realizados mediante SINPE Móvil. Su objetivo es automatizar la verificación de comprobantes de pago y notificar al sistema de Punto de Venta (POS) cuando una transacción ha sido confirmada.

Esta API forma parte de un proyecto académico del curso de Ingeniería de Software, cuyo propósito es simular una solución tecnológica que reduzca fraudes, errores humanos y tiempos de espera en los comercios.

## Requisitos

Antes de empezar, instala lo siguiente:

- Python 3.10 o superior
- pip (administrador de paquetes de Python)
- Git

Opcional pero recomendado:

- Entorno virtual (`venv`) para aislar dependencias

## Clonar el proyecto

```bash
git clone https://github.com/ImJonathan365/sinpe-bridge-api.git
cd sinpe-bridge-api
code .
```

## Instalacion y ejecucion en Linux

1. Crear entorno virtual:

```bash
python3 -m venv venv
```

2. Activar entorno virtual:

```bash
source venv/bin/activate
```

3. Instalar dependencias:

```bash
pip install -r requirements.txt
```

4. Levantar la API con recarga automatica:

```bash
uvicorn app.main:app --reload
```

## Instalacion y ejecucion en Windows

1. Crear entorno virtual:

```powershell
py -m venv venv
```

2. Activar entorno virtual (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

Si usas CMD:

```bat
venv\Scripts\activate.bat
```

3. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

4. Levantar la API con recarga automatica:

```powershell
uvicorn app.main:app --reload
```

## Probar que funciona

Con la API corriendo, abre en tu navegador:

- `http://127.0.0.1:8000/` (debe responder `Hola mundo`)

## Dependencias principales

El proyecto usa, entre otras:

- `fastapi`
- `uvicorn`
- `pydantic`

Todas estan definidas en `requirements.txt`.

## Estructura del proyecto (explicacion simple)

La API esta organizada por capas para que sea mas facil de mantener y escalar.

- `app/main.py`:
	punto de entrada de FastAPI. Aqui se crea la aplicacion y se exponen endpoints base.

- `app/api/`:
	define rutas y endpoints HTTP (lo que recibe cada request).
	Ejemplo: archivos en `app/api/v1/endpoints/` agrupan endpoints por modulo (payments, orders, monitoring, etc.).

- `app/domain/`:
	contiene la logica del negocio. Esta capa es de las mas importantes y normalmente incluye:
	- `models.py`: representa entidades de negocio o estructuras de datos internas.
	- `schemas.py`: define contratos de entrada/salida para validar datos con Pydantic.
	- `service.py`: concentra casos de uso y reglas de negocio (la logica principal).
	- `repository.py`: encapsula acceso a datos para no mezclar SQL/DB directo dentro de servicios.

	Idea clave: los endpoints llaman a servicios, y los servicios usan modelos/schemas/repositorios para resolver cada caso de negocio.

- `app/infrastructure/`:
	integra dependencias externas y detalles tecnicos.
	Ejemplos actuales:
	- `db/`: sesion, base y modelos de persistencia.
	- `alerts/`: envio de alertas por correo o Telegram.
	- `ai/`: analisis de imagen/comprobante con integraciones de AI.
	- `pos/`: cliente para notificar al sistema POS.
	- `sms/`: procesamiento y extraccion de texto de mensajes.

- `app/core/`:
	configuraciones globales y seguridad.

- `app/shared/`:
	piezas reutilizables en todo el proyecto: constantes, enums y helpers comunes.

- `test/`:
	pruebas del proyecto.

Flujo simplificado de una solicitud:

1. El cliente hace una peticion a un endpoint en `app/api/...`.
2. El endpoint delega el trabajo a un servicio en `app/domain/...`.
3. El servicio valida y transforma datos con `schemas.py` / `models.py`.
4. Si hace falta persistencia o integracion externa, usa repositorios o componentes de `app/infrastructure/...`.
5. La API responde con el resultado al cliente.

