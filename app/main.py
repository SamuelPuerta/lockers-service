"""Microservicio FastAPI: ingesta en tiempo real de logs, conteo por modulo y exportacion a Excel."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .excel import build_workbook
from .parser import parse_line
from .store import TZ, Store

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class Tailer:
    """Sigue un archivo de log: procesa lo existente y luego solo lo nuevo (tolera truncado/rotacion)."""

    def __init__(self, path, store):
        self.path, self.store, self.pos, self.buf = path, store, 0, b""

    def step(self):
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return
        if size < self.pos:
            self.pos, self.buf = 0, b""
        if size == self.pos:
            return
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            self.buf += f.read()
            self.pos = f.tell()
        *lines, self.buf = self.buf.split(b"\n")  # la ultima linea parcial queda en el buffer
        rows = [r for r in (parse_line(x.decode("utf-8", "replace")) for x in lines) if r]
        if rows:
            self.store.insert_many(rows)


async def _tail_loop(tailer, interval=1.0):
    while True:
        await asyncio.to_thread(tailer.step)
        await asyncio.sleep(interval)


def create_app(db_path=None, log_path=None, count_events=None) -> FastAPI:
    db_path = db_path or os.getenv("DB_PATH", "data/events.db")
    log_path = log_path if log_path is not None else os.getenv("LOG_PATH")
    if count_events is None:
        count_events = [e.strip() for e in os.getenv("COUNT_EVENTS", "").split(",") if e.strip()]
    store = Store(db_path)

    @asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(_tail_loop(Tailer(log_path, store))) if log_path else None
        yield
        if task:
            task.cancel()

    api = FastAPI(title="Lockers Service", lifespan=lifespan)

    def _fecha(v):
        if v is None:
            return datetime.now(TZ).strftime("%Y-%m-%d")
        if v == "all":
            return None
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            raise HTTPException(422, "fecha debe ser YYYY-MM-DD o 'all'")

    def _eventos(v):
        return [e.strip() for e in v.split(",") if e.strip()] if v else count_events

    def _snapshot(fecha, evento):
        f, ev = _fecha(fecha), _eventos(evento)
        m = store.counts(f, ev)
        return {"fecha": f or "todas", "eventos": ev or "todos", "total": sum(m.values()),
                "modulos": {str(k): v for k, v in m.items()}}

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.post("/ingest")
    async def ingest(request: Request):
        """Cuerpo text/plain con una o varias lineas de log (o JSON sueltos). Idempotente por comando.id."""
        lines = (await request.body()).decode("utf-8", "replace").splitlines()
        lines = [x for x in lines if x.strip()]
        rows = [r for r in map(parse_line, lines) if r]
        new, dup = await asyncio.to_thread(store.insert_many, rows)
        return {"recibidas": len(lines), "nuevas": new, "duplicadas": dup, "invalidas": len(lines) - len(rows)}

    @api.get("/counts")
    def counts(fecha: str | None = None, evento: str | None = None):
        return _snapshot(fecha, evento)

    @api.get("/export.xlsx")
    def export(fecha: str | None = None, modulo: int | None = None, evento: str | None = None):
        f, ev = _fecha(fecha), _eventos(evento)
        data = build_workbook(store.rows(f, ev, modulo), f, ev)
        name = f"registros_{f or 'todas'}{f'_modulo{modulo}' if modulo is not None else ''}.xlsx"
        return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @api.get("/stream")
    async def stream(request: Request, fecha: str | None = None, evento: str | None = None):
        """Server-Sent Events: emite los conteos cada vez que llegan registros nuevos."""
        _fecha(fecha)  # valida antes de abrir el stream

        async def gen():
            last, idle = -1, 0
            while not await request.is_disconnected():
                if store.version != last:
                    last, idle = store.version, 0
                    yield f"data: {json.dumps(_snapshot(fecha, evento))}\n\n"
                else:
                    idle += 1
                    if idle % 15 == 0:
                        yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return api


app = create_app()
