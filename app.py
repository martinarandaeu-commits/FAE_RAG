"""Entrada ASGI compatible: ejecutar uvicorn app:app."""

from fae_rag.api import Consulta, crear_app
from fae_rag.generacion import generar_respuesta_gemini

app = crear_app()
