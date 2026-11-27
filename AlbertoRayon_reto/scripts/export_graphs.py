"""Escribe en ``doc/graphs.md`` los grafos de LangGraph como diagramas Mermaid.

Uso: ``python scripts/export_graphs.py``. Los diagramas salen del código, así que
la documentación no se desfasa de los agentes.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# pylint: disable=wrong-import-position
from app.config import load_settings  # noqa: E402
from app.service import HRService  # noqa: E402

TITLES = {
    "supervisor": "Supervisor con especialistas",
    "react": "Agente ReAct (directorio y vacaciones)",
    "reflection": "Agente de reflexión (resúmenes)",
}


def main() -> int:
    """Genera el documento de grafos."""
    service = HRService(load_settings({}))
    parts = ["# Grafos de los agentes", "",
             "Generado con `python scripts/export_graphs.py`. No editar a mano."]
    for name, diagram in service.graphs().items():
        parts += ["", f"## {TITLES[name]}", "", "```mermaid", diagram.strip(), "```"]
    (ROOT / "doc" / "graphs.md").write_text("\n".join(parts) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
