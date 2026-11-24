"""Adaptador HTTP del agente, separado de la lógica de dominio."""

import json
import logging
import os
from asyncio import CancelledError, create_task, sleep
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .agente import AgenteHibrido
from .configuracion import BASE
from .fabrica import crear_agente
from .orientacion import canales_ayuda, nivel_riesgo

logger = logging.getLogger(__name__)


class Consulta(BaseModel):
    """Validación de entrada en el límite HTTP."""

    pregunta: str = Field(min_length=3, max_length=2000)
    categoria: str | None = Field(default=None, pattern=r"^CAT-0[1-5]$")
    contexto: list[Annotated[str, Field(min_length=3, max_length=2000)]] = Field(
        default_factory=list, max_length=4
    )
    guardar: bool = False


class Evaluacion(BaseModel):
    util: bool = Field(strict=True)


def crear_app(agente: AgenteHibrido | None = None) -> FastAPI:
    """Permitir ejecutar la API con un agente real o un doble de pruebas."""
    from .corpus_render import archivo_corpus

    servicio = agente if agente is not None else crear_agente()
    demo = os.getenv("FAE_MODO") == "demo"
    portal = os.getenv("FAE_PORTAL") == "1"
    corpus = archivo_corpus() if agente is None else None
    vectores_corpus = 0

    if portal:
        from .portal_auth import cifrador, inicializar_admin, limitar, titular
        from .portal_cuentas import guardar_turno, router_cuentas
        from .portal_db import ajuste, preparar_portal, purgar_vencidos, transaccion
        from .portal_gestion import canales_portal, router_gestion

    async def retencion():
        while True:
            try:
                await run_in_threadpool(purgar_vencidos)
            except Exception:
                logger.warning("La tarea de retención de datos requiere revisión.")
            await sleep(3600)

    @asynccontextmanager
    async def iniciar(_api: FastAPI):
        nonlocal vectores_corpus
        if corpus is not None:
            from .corpus_render import cargar_corpus
            from .embeddings_render import crear_cliente

            vectores_corpus = await run_in_threadpool(cargar_corpus, corpus)
            await run_in_threadpool(crear_cliente)
        elif demo and agente is None:
            from .demostracion import preparar_demo

            await run_in_threadpool(preparar_demo)
        tarea = None
        if portal:
            cifrador()
            await run_in_threadpool(preparar_portal)
            await run_in_threadpool(inicializar_admin)
            if not demo:
                from .metricas_demo import ESQUEMA_METRICAS
                from .portal_indice import preparar_indice_portal

                with transaccion() as cur:
                    cur.execute(ESQUEMA_METRICAS)
                await run_in_threadpool(preparar_indice_portal)
            tarea = create_task(retencion())
        try:
            yield
        finally:
            if tarea:
                tarea.cancel()
                with suppress(CancelledError):
                    await tarea

    api = FastAPI(title="Agente híbrido RAG FAE", version="2.2.0", lifespan=iniciar)

    @api.exception_handler(RequestValidationError)
    async def error_validacion(_request: Request, error: RequestValidationError):
        campos = [".".join(str(x) for x in e["loc"]) for e in error.errors()]
        return JSONResponse(
            status_code=422,
            content={"detail": "Revisa los campos indicados.", "campos": campos},
        )

    @api.middleware("http")
    async def proteger_respuestas(request: Request, siguiente):
        if portal and request.method not in ("GET", "HEAD", "OPTIONS"):
            origen = request.headers.get("origin")
            esperado = os.getenv("FAE_URL_PUBLICA", "").rstrip("/")
            if origen and origen not in (esperado, str(request.base_url).rstrip("/")):
                return JSONResponse(
                    status_code=403, content={"detail": "Origen no permitido."}
                )
        respuesta = await siguiente(request)
        if request.url.path.startswith("/api/") or request.url.path == "/portal":
            respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        return respuesta

    if portal:
        api.include_router(router_cuentas(demo))
        api.include_router(router_gestion(demo))

        @api.get("/portal")
        def portal_web():
            return FileResponse(BASE / "web" / "portal.html")

    @api.get("/assets/fae.css", include_in_schema=False)
    def estilos_compartidos():
        return FileResponse(BASE / "web" / "fae.css", media_type="text/css")

    @api.get("/")
    def inicio():
        archivo = BASE / "web" / "index.html"
        return (
            FileResponse(archivo) if archivo.is_file() else {"documentacion": "/docs"}
        )

    @api.get("/api/salud")
    def salud():
        return {
            "estado": "activo",
            "servicio": "RAG FAE",
            "agente": "hibrido_reactivo_deliberativo",
            "modo": "demo" if demo else "documental",
            "portal": portal,
            **(
                {"corpus": {"tipo": "documental", "vectores": vectores_corpus}}
                if corpus is not None
                else {}
            ),
            "modelo_chat": None
            if demo or portal
            else os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash-lite"),
        }

    @api.get("/api/ayuda")
    def ayuda(region: str | None = None):
        if region and len(region) > 80:
            raise HTTPException(422, "Región inválida.")
        canales = canales_ayuda()
        if portal:
            try:
                canales = canales_portal(region) or canales
            except Exception:
                logger.warning(
                    "No se pudo leer la configuración institucional de ayuda."
                )
        return {"canales": canales, "demo": demo}

    @api.post("/api/demo/evaluar", status_code=202)
    def evaluar(datos: Evaluacion, request: Request):
        if not demo and not portal:
            raise HTTPException(status_code=404)
        from .metricas_demo import registrar_evaluacion

        if portal:
            limitar("evaluar", request, 25)
        registrar_evaluacion(datos.util)
        return {"estado": "recibida"}

    @api.get("/api/demo/metricas")
    def metricas(clave: Annotated[str, Header(alias="X-FAE-Demo-Key")] = ""):
        from .metricas_demo import acceso_configurado, leer_metricas

        if not demo or not acceso_configurado(
            os.getenv("FAE_METRICAS_CLAVE", ""), clave
        ):
            raise HTTPException(status_code=404)
        return leer_metricas()

    @api.post("/api/consultar")
    def consultar(datos: Consulta, request: Request):
        contexto = tuple(datos.contexto)
        riesgo = nivel_riesgo(datos.pregunta, contexto)
        opciones = {}
        if portal and riesgo == "rojo":
            opciones["canales_configurados"] = ayuda()["canales"]
        try:
            if portal and riesgo != "rojo":
                limitar("consulta", request, 45)
                persona = titular(request, opcional=True)
                if persona and persona["rol"] == "familia":
                    opciones["tramo"] = persona["perfil"].get("tramo")
                with transaccion() as cur:
                    opciones["limite"] = ajuste(cur, "limite_fragmentos", 3)
                    if not demo and os.getenv("RAG_EMBEDDING_BACKEND") == "local":
                        opciones["similitud_minima"] = ajuste(
                            cur, "umbral_local", servicio.similitud_minima
                        )
            resultado = servicio.consultar(
                datos.pregunta, datos.categoria, contexto=contexto, **opciones
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("No se pudo recuperar evidencia para la consulta.")
            raise HTTPException(
                status_code=503,
                detail="No se pudo consultar el servicio. Revisa la terminal.",
            ) from exc
        if portal and datos.guardar and riesgo != "rojo":
            try:
                guardar_turno(request, datos.pregunta, resultado)
            except Exception:
                resultado["historial"] = "no_guardado"
                logger.warning("No se pudo guardar una entrada del historial privado.")
        if (demo or portal) and riesgo != "rojo":
            from .metricas_demo import registrar_consulta

            try:
                registrar_consulta(
                    resultado["orientacion"]["nivel"], resultado["agente"]["modo"]
                )
            except Exception:
                logger.warning("No se pudo registrar un contador anónimo de la demo.")
        return resultado

    @api.post("/api/consultar/stream")
    def consultar_en_progreso(datos: Consulta, request: Request):
        if not datos.pregunta.strip() or len(datos.pregunta.strip()) < 3:
            raise HTTPException(status_code=422, detail="Escribe una consulta válida.")

        def eventos():
            if nivel_riesgo(datos.pregunta, tuple(datos.contexto)) != "rojo":
                yield sse("estado", {"mensaje": "Revisando la consulta…"})
            try:
                resultado = consultar(datos, request)
            except HTTPException as exc:
                yield sse("error", {"mensaje": exc.detail})
                return
            # La respuesta se verifica completa antes de entregarla.
            yield sse("resultado", resultado)
            yield sse("fin", {})

        return StreamingResponse(
            eventos(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    return api


def sse(evento: str, datos: dict) -> str:
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False)}\n\n"
