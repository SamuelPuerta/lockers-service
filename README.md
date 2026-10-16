# Lockers Service

## Prueba Técnica - Protección (Canales Digitales)

### Por: Samuel Puerta

Microservicio en Python (FastAPI) de "Apertura de Casilleros" para un espacio de coworking. Recibe registros en tiempo real, los estructura (FECHA, HORA, NÚMERO DE MODULO), deduplica y entrega el resultado en Excel bajo demanda.

## Estructura

```text
lockers-service/
├── app/
│   ├── main.py            # API, fábrica create_app, Tailer y SSE
│   ├── parser.py          # línea de log -> registro plano
│   ├── store.py           # SQLite: persistencia, deduplicación y consultas
│   └── excel.py           # construcción del libro Excel
├── BD/                    # archivo de entrada (txt del log de Splunk)
│   └── 1720452779_5118875.txt
├── data/                  # se genera al ejecutar
├── tests/
│   └── test_service.py    # Cliente de Prueba
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Ejecutar

### Local

```bash
python3 -m venv .venv && source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

### Docker

```bash
docker build -t lockers .
docker run -p 8000:8000 -v lockers-data:/data lockers
```

Documentación interactiva: http://localhost:8000/docs

## Ejecutar usando el archivo txt (carpeta BD)

Con `LOG_PATH` el servicio lee el archivo de `BD/`, procesa lo existente y luego sigue solo con lo nuevo.

### Local

```bash
LOG_PATH=./BD/1720452779_5118875.txt uvicorn app.main:app --port 8000
```

```powershell
# Windows PowerShell
$env:LOG_PATH=".\BD\1720452779_5118875.txt"; uvicorn app.main:app --port 8000
```

La base se crea en `data/events.db`; el txt de `BD/` no se modifica.

### Docker

La imagen no incluye `BD/`, por lo que se monta como volumen de solo lectura:

```bash
docker build -t lockers .
docker run -d --name lockers -p 8000:8000 \
  -v lockers-data:/data \
  -v "$(pwd)/BD:/logs:ro" \
  -e LOG_PATH=/logs/1720452779_5118875.txt \
  lockers
```

```powershell
# Windows PowerShell: reemplazar "$(pwd)/BD" por "${PWD}/BD"
```

- Para ver el procesamiento: `docker logs -f lockers`.

### Verificar

Esperar 1 o 2 segundos y consultar:

```bash
curl "localhost:8000/counts?fecha=2024-07-06"
```

Resultado esperado: `total` 2730, módulo `342` = 1386 y módulo `355` = 1344. Si el conteo da 0, revisar que la ruta de `LOG_PATH` exista (el servicio no avisa si el archivo no se encuentra).

## Endpoints

| Método | Ruta                                  | Qué hace                                                                                        |
| ------ | ------------------------------------- | ----------------------------------------------------------------------------------------------- |
| POST   | `/ingest`                             | Cuerpo `text/plain` con una o más líneas de log (o JSON sueltos). Idempotente por `comando.id`. |
| GET    | `/counts?fecha=YYYY-MM-DD&evento=`    | Conteo por módulo (JSON). `fecha=all` = todas; por defecto, hoy en hora Colombia.               |
| GET    | `/export.xlsx?fecha=&modulo=&evento=` | Excel: Base_Estructurada, Resumen_por_Modulo, Resumen_por_Hora, Notas.                          |
| GET    | `/stream?fecha=`                      | Server-Sent Events: emite los conteos cada vez que llegan registros nuevos.                     |
| GET    | `/health`                             | Estado del servicio.                                                                            |

```bash
curl -X POST --data-binary @BD/1720452779_5118875.txt localhost:8000/ingest

curl "localhost:8000/counts?fecha=2024-07-06"

curl -o registros.xlsx "localhost:8000/export.xlsx?fecha=2024-07-06"

curl -N "localhost:8000/stream?fecha=2024-07-06"
```

## Tiempo real

- **Push:** cualquier sistema (consumidor de la cola, Splunk, un script) envía líneas a `/ingest`.
- **Pull:** con `LOG_PATH` el servicio sigue el archivo, procesa lo existente y luego solo lo nuevo (tolera truncado y rotación).
- **Consumo:** `/stream` empuja los conteos a un tablero; `/export.xlsx` genera el Excel con los datos al momento de la petición.

## Decisiones de diseño

- **Deduplicación por `comando.id`:** cada mensaje llega dos veces con distinto `event_id`. La PRIMARY KEY de SQLite lo resuelve y hace la ingesta idempotente.
- **Hora:** el `timestamp` del JSON es epoch UTC en milisegundos; se convierte a `America/Bogota`.
- **Qué se cuenta:** el archivo de prueba contiene solo `healthcheck.check` (pulsos de salud), no aperturas. Se guarda el tipo de evento y `COUNT_EVENTS` (o `?evento=`) define cuál contar; cuando exista el evento de apertura basta configurarlo, sin tocar código.
- **Excel:** los resúmenes son fórmulas (`COUNTIFS`, `SUMPRODUCT`) sobre la hoja base; Excel las calcula al abrir. Un proceso, un worker: `version` del stream vive en memoria.

## Pruebas

```bash
python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements-dev.txt

python -m pytest -q
```

Resultado con el archivo real: 5.460 líneas recibidas, 2.730 únicas; módulo 342 = 1.386 y módulo 355 = 1.344.
