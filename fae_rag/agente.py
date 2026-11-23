"""Agente híbrido con reglas reactivas y ejecución de un plan RAG acotado."""

import logging
import re
from dataclasses import dataclass

from .contratos import Documento, Generador, Recuperador
from .orientacion import (
    canales_ayuda,
    consulta_contextual,
    contiene_identificadores,
    nivel_riesgo,
)
from .taxonomia import CATEGORIAS
from .texto import normalizar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanConsulta:
    """Decisión explícita, observable y reproducible de la capa de control."""

    ruta: str
    categoria: str | None
    pasos: tuple[str, ...]


def planificar(
    pregunta: str, categoria: str | None = None, riesgo: str | None = None
) -> PlanConsulta:
    """Aplicar reglas antes de decidir qué herramientas necesita la consulta."""
    if not pregunta or not 3 <= len(pregunta.strip()) <= 2000:
        raise ValueError("La pregunta debe tener entre 3 y 2000 caracteres.")
    if categoria is not None and categoria not in CATEGORIAS:
        raise ValueError("Categoría inválida.")
    if riesgo == "rojo":
        return PlanConsulta(
            "derivacion", categoria, ("clasificar_riesgo", "mostrar_ayuda")
        )
    texto = normalizar(pregunta).strip(" ¡!¿?.,")
    if texto in ("hola", "buenas", "buenos dias", "buenas tardes", "buenas noches"):
        return PlanConsulta("saludo", categoria, ("responder_saludo",))
    if texto in ("ayuda", "que puedes hacer", "como funciona", "categorias"):
        return PlanConsulta("ayuda", categoria, ("mostrar_alcance_y_categorias",))
    return PlanConsulta(
        "consulta",
        categoria,
        (
            "recuperar_evidencia_hibrida",
            "evaluar_evidencia",
            "generar_respuesta",
            "validar_identificadores_citados",
        ),
    )


def fuentes_publicas(documentos: list[Documento]) -> list[dict]:
    """Adaptar evidencia al contrato HTTP que ya utiliza la interfaz."""
    fuentes = []
    for doc in documentos:
        meta = doc.get("metadata") or {}
        fuentes.append(
            {
                "chunk_id": doc["chunk_id"],
                "categoria": doc["categoria"],
                "fuente": doc["fuente"],
                "seccion": doc["seccion"],
                "similitud": doc["similitud"],
                "titulo": meta.get("titulo", ""),
                "alcance": meta.get("alcance_texto", "ficha_bibliografica_de_matriz"),
                "autor": meta.get("autor", ""),
                "anio": meta.get("anio", ""),
                "enlace": meta.get("enlace", ""),
                "pagina": meta.get("pagina"),
                "licencia": meta.get("licencia", ""),
                "extracto": doc["contenido"].split("[Texto]: ", 1)[-1][:1800],
                "vigencia": meta.get("vigencia", "")
                or (
                    "Vigencia diferida según el documento consultado"
                    if "vigencia_diferida" in meta.get("alcance_texto", "")
                    else ""
                ),
            }
        )
    return fuentes


class AgenteHibrido:
    """Combinar reglas, recuperación y LLM mediante dependencias sustituibles."""

    def __init__(
        self,
        recuperar: Recuperador,
        generar: Generador | None,
        similitud_minima: float = 0.35,
    ) -> None:
        if not -1 <= similitud_minima <= 1:
            raise ValueError("La similitud mínima debe estar entre -1 y 1.")
        self.recuperar = recuperar
        self.generar = generar
        self.similitud_minima = similitud_minima

    def consultar(
        self,
        pregunta: str,
        categoria: str | None = None,
        *,
        contexto: tuple[str, ...] = (),
        tramo: str | None = None,
        limite: int = 3,
        similitud_minima: float | None = None,
        canales_configurados: list[dict] | None = None,
    ) -> dict:
        """Ejecutar el plan con abstención y alternativa extractiva acotada."""
        riesgo = nivel_riesgo(pregunta, contexto)
        plan = planificar(pregunta, categoria, riesgo)
        pasos = []

        def resultado(respuesta: str, modo: str, documentos: list[Documento]) -> dict:
            return {
                "respuesta": respuesta,
                "fuentes": fuentes_publicas(documentos),
                "orientacion": {
                    "nivel": riesgo,
                    "contactar_dupla": riesgo in ("rojo", "amarillo"),
                    "canales": (
                        canales_configurados
                        if canales_configurados is not None
                        else canales_ayuda()
                    )
                    if riesgo == "rojo"
                    else [],
                    "puente_copiable": riesgo in ("rojo", "amarillo"),
                },
                "agente": {
                    "tipo": "hibrido_reactivo_deliberativo",
                    "ruta": plan.ruta,
                    "modo": modo,
                    "categoria": plan.categoria,
                    "plan": list(plan.pasos),
                    "pasos_ejecutados": pasos.copy(),
                },
            }

        if plan.ruta == "derivacion":
            pasos.extend(plan.pasos)
            return resultado(
                "Busca ayuda humana ahora. Si hay peligro inmediato, "
                "comunícate con el servicio de emergencia de tu zona.",
                "derivacion",
                [],
            )
        consulta = consulta_contextual(pregunta, contexto)
        if contiene_identificadores(" ".join((*contexto, pregunta))):
            return resultado(
                "Para proteger la privacidad, comienza una consulta nueva "
                "sin nombres, teléfonos, correos, RUT ni detalles identificables.",
                "privacidad",
                [],
            )

        if plan.ruta == "saludo":
            pasos.append("responder_saludo")
            return resultado(
                "Hola. Puedes consultar sobre familias de acogida y sus fuentes bibliográficas.",
                "reglas",
                [],
            )
        if plan.ruta == "ayuda":
            pasos.append("mostrar_alcance_y_categorias")
            categorias = "\n".join(f"{k}: {v}" for k, v in CATEGORIAS.items())
            return resultado(
                "Respondo con evidencia de las matrices y textos revisados.\n"
                + categorias,
                "reglas",
                [],
            )

        consulta = (
            f"{consulta} (Tramo orientativo: {tramo} años.)" if tramo else consulta
        )
        umbral = self.similitud_minima if similitud_minima is None else similitud_minima
        documentos = self.recuperar(consulta, categoria=plan.categoria, limite=limite)
        pasos.extend(("recuperar_evidencia_hibrida", "evaluar_evidencia"))
        # El umbral es una heurística configurable, no una medida de confianza.
        documentos = [
            d
            for d in documentos
            if (
                d["similitud"] >= umbral
                or d.get("metadata", {}).get("coincidencia_textual_curada")
            )
            and (categoria is None or d["categoria"] == categoria)
        ]
        if not documentos:
            return resultado(
                "No encontré evidencia suficiente para responder. Prueba con una pregunta más específica.",
                "abstencion",
                [],
            )
        if self.generar is None:
            pasos.append("extraer_evidencia")
            return resultado(self._extraer(documentos), "extractivo", documentos)
        pasos.append("generar_respuesta")
        try:
            respuesta = self.generar(consulta, documentos)
        except Exception:
            logger.warning("La generación falló; se devolverán extractos de evidencia.")
            return resultado(self._extraer(documentos), "extractivo", documentos)
        pasos.append("validar_identificadores_citados")
        if not isinstance(respuesta, str) or not respuesta.strip():
            return resultado(self._extraer(documentos), "extractivo", documentos)
        citados = set(re.findall(r"\b(?:ref|web)_[a-zA-Z0-9]+\b", respuesta))
        permitidos = {d["chunk_id"] for d in documentos}
        if not citados or not citados.issubset(permitidos):
            return resultado(self._extraer(documentos), "extractivo", documentos)
        return resultado(
            respuesta,
            "generativo",
            [doc for doc in documentos if doc["chunk_id"] in citados],
        )

    @staticmethod
    def _extraer(documentos: list[Documento]) -> str:
        """Devolver extractos identificados cuando no hay síntesis verificable."""
        return "Extractos de las fuentes recuperadas:\n\n" + "\n\n".join(
            f"[{doc['chunk_id']}] {doc['contenido'][:1000]}" for doc in documentos
        )
