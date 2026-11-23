"""Composición de adaptadores concretos fuera del núcleo del agente."""

import os

from .agente import AgenteHibrido
from .configuracion import cargar_entorno
from .generacion import generar_respuesta_gemini
from .recuperacion import buscar


def crear_agente() -> AgenteHibrido:
    """Construir el agente sin abrir conexiones ni consumir API."""
    cargar_entorno()
    if os.getenv("FAE_MODO") == "demo":
        from .demostracion import buscar_demo

        base = AgenteHibrido(buscar_demo, None, similitud_minima=0.01)
        return con_curaduria(base)
    backend = os.getenv("RAG_EMBEDDING_BACKEND", "gemini").lower()
    if os.getenv("FAE_PORTAL") == "1" and backend != "local":
        raise RuntimeError("El portal documental requiere RAG_EMBEDDING_BACKEND=local.")
    umbral = (
        os.getenv("RAG_SIMILITUD_MINIMA_LOCAL", "0.84")
        if backend == "local"
        else os.getenv("RAG_SIMILITUD_MINIMA", "0.35")
    )
    base = AgenteHibrido(
        recuperar=buscar,
        generar=None if os.getenv("FAE_PORTAL") == "1" else generar_respuesta_gemini,
        similitud_minima=float(umbral),
    )
    return con_curaduria(base)


def con_curaduria(agente: AgenteHibrido) -> AgenteHibrido:
    if os.getenv("FAE_PORTAL") != "1":
        return agente
    if os.getenv("FAE_MODO") == "demo":
        from .portal_gestion import buscar_curado
    else:
        from .portal_indice import buscar_indexados as buscar_curado

    base = agente.recuperar

    def recuperar(pregunta, categoria=None, limite=3):
        curados = buscar_curado(pregunta, categoria, limite)
        try:
            otros = base(pregunta, categoria=categoria, limite=limite)
        except Exception:
            if not curados:
                raise
            otros = []
        return (curados + otros)[:limite]

    return AgenteHibrido(recuperar, agente.generar, agente.similitud_minima)
