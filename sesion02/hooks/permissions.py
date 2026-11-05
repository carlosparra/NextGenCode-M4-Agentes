"""Hook PreToolUse: cada agente escribe solo en sus carpetas (mínima agencia).

Claude Code llama a este script antes de cada herramienta y le pasa por stdin un
JSON con ``agent_type`` (el agente), ``tool_name`` y ``tool_input``. Si el script
termina con código 2, la herramienta se bloquea y el agente lee el motivo.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Dónde puede escribir cada agente. Quien escribe el código no escribe sus pruebas.
WRITABLE = {
    "architect": ["output/", "product/doc/"],
    "qa-unit": ["product/tests/"],
    "developer": ["product/app/", "product/data/", "product/requirements.txt"],
    "observability": ["product/app/", "product/requirements.txt", "product/README.md"],
    "qa-style": ["output/qa-review.md"],
}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def check(event: dict) -> str | None:
    """Devuelve el motivo del bloqueo, o ``None`` si la herramienta puede correr."""
    agent = event.get("agent_type")
    if agent not in WRITABLE or event.get("tool_name") not in WRITE_TOOLS:
        return None
    target = (ROOT / event.get("tool_input", {}).get("file_path", "")).resolve()
    path = target.relative_to(ROOT).as_posix() if target.is_relative_to(ROOT) else ""
    if any(path == allowed or path.startswith(allowed) for allowed in WRITABLE[agent]):
        return None
    allowed = ", ".join(WRITABLE[agent])
    return f"{agent} no puede escribir {path or target}. Solo puede en: {allowed}"


if __name__ == "__main__":
    REASON = check(json.load(sys.stdin))
    if REASON:
        print(REASON, file=sys.stderr)
    sys.exit(2 if REASON else 0)
