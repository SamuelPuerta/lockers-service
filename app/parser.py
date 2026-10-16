"""Parseo de una linea de log de Splunk (o de un JSON suelto) a un registro plano."""
import json

_BODY = "msg_body="


def parse_line(line: str):
    """Devuelve {id, evento, modulo, ts_ms} o None si la linea no es valida."""
    line = line.strip()
    if not line:
        return None
    raw = line.split(_BODY, 1)[1] if _BODY in line else line
    try:
        cmd = json.loads(raw)["comando"]
        return {
            "id": str(cmd["id"]),
            "evento": str(cmd["nombre"]),
            "modulo": int(cmd["payload"]["moduloId"]),
            "ts_ms": int(cmd["timestamp"]),
        }
    except (ValueError, KeyError, TypeError):
        return None
