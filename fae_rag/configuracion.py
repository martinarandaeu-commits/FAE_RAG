"""Rutas y configuración compartidas, sin conexiones al importar módulos."""

import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ARCHIVO = (
    BASE
    / "data"
    / "Matriz_bibliografica_FAE_autocuidado_transiciones_USS_2026 (1).xlsx"
)
SALIDA_URLS = BASE / "resultados" / "urls"
HOJAS = (
    "Transiciones y adopción",
    "USS preparación previa",
    "Matriz completa",
    "Orientaciones preacogimiento",
)


def cargar_entorno() -> None:
    """Leer credenciales locales solo al ejecutar una operación externa."""
    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")


def parametros_postgres() -> dict:
    """Obtener una configuración única para todos los adaptadores de BD."""
    cargar_entorno()
    if url := os.getenv("DATABASE_URL"):
        return {"dsn": url, "connect_timeout": 5}
    return {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "fae_rag"),
        "user": os.getenv("PGUSER", "postgres"),
        "password": os.getenv("PGPASSWORD"),
        "connect_timeout": 10,
    }
