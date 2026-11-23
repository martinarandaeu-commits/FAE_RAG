"""Taxonomía única y clasificación determinista de referencias."""

import re

from .texto import normalizar

CATEGORIAS = {
    "CAT-01": "Marco Normativo y Técnico",
    "CAT-02": "Autocuidado y Bienestar del Cuidador",
    "CAT-03": "Transiciones y Adopción",
    "CAT-04": "Preparación Previa y Formación",
    "CAT-05": "Experiencia y Perspectiva de NNA",
}


def categoria_por_contexto(
    seccion: str, titulo: str, hoja: str
) -> tuple[str | None, str]:
    """Prioriza la seccion documental. Evita CAT-03 por defecto indiscriminado."""
    s = normalizar(seccion)
    t = normalizar(titulo)
    h = normalizar(hoja)
    if any(
        x in s
        for x in (
            "normativ",
            "marco legal",
            "legislacion",
            "leyes",
            "resolucion",
            "directrices",
        )
    ):
        return "CAT-01", "seccion"
    if any(
        x in s
        for x in (
            "experiencia del",
            "experiencia de nna",
            "perspectiva de",
            "voz del",
            "vivencias de",
            "estabilidad del nna",
        )
    ):
        return "CAT-05", "seccion"
    if any(
        x in s
        for x in (
            "autocuidado",
            "duelo",
            "bienestar del cuidador",
            "burnout",
            "estres",
            "trauma secundario",
        )
    ):
        return "CAT-02", "seccion"
    if any(
        x in s
        for x in (
            "preparacion",
            "preacogimiento",
            "postulacion",
            "formacion",
            "requisitos",
        )
    ):
        return "CAT-04", "seccion"
    if any(
        x in s
        for x in (
            "transicion",
            "adopcion",
            "desvinculacion",
            "enlace",
            "continuidad de vinculos",
        )
    ):
        return "CAT-03", "seccion"
    if h == "orientaciones preacogimiento" or h == "uss preparacion previa":
        return "CAT-04", "hoja"
    # Titulo es señal secundaria, no analizar indiscriminadamente todo el texto.
    if re.search(r"\b(ley|decreto|normativa|directrices)\b", t):
        return "CAT-01", "titulo"
    if any(
        x in t
        for x in (
            "voz de los ninos",
            "perspectiva de los ninos",
            "experiencia de ninos",
            "vivencias de ninos",
        )
    ):
        return "CAT-05", "titulo"
    if any(
        x in t for x in ("preparacion", "formacion", "preacogimiento", "postulacion")
    ):
        return "CAT-04", "titulo"
    if any(
        x in t
        for x in ("autocuidado", "estres", "burnout", "duelo", "bienestar del cuidador")
    ):
        return "CAT-02", "titulo"
    if any(x in t for x in ("adopcion", "transicion", "desvinculacion")):
        return "CAT-03", "titulo"
    if h == "matriz completa":
        return "CAT-02", "hoja (revision recomendada)"
    if h == "transiciones y adopcion":
        return "CAT-03", "hoja (respaldo; revisar si aplica)"
    return None, "revision manual"
