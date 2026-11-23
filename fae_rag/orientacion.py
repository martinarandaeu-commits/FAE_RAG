"""Derivación conservadora para la demostración y protección de entradas."""

import json
import os
import re
from pathlib import Path

from .texto import normalizar

ROJO = (
    r"\b(?:abuso sexual|violacion|violaron|violencia en curso|agresion en curso)\b",
    r"\b(?:maltrat[ao]|golpean|golpeando|amenaza con (?:matar|un arma)|"
    r"(?:la|lo|me) toco (?:en|sus) (?:el colegio|sus partes|las partes|partes intimas))\b",
    r"\b(?:no (?:respira|responde|despierta)|inconsciente|"
    r"riesgo vital|peligro (?:ahora|inmediato)|sobredosis|se esta ahogando)\b",
    r"\b(?:perdio el conocimiento|perder el conocimiento|esta sangrando (?:mucho|sin parar)|"
    r"sangrado abundante)\b",
    r"\b(?:(?:quiero|voy a|pienso en|dijo que quiere) "
    r"(?:matarme|suicidarme|suicidarse|morir|hacerme dano|hacerse dano)|"
    r"(?:se quiere|se va a) (?:matar|suicidar)|intento de suicidio)\b",
)
AMARILLO = (
    r"\b(?:desbordad[ao]|angustia intensa|no doy mas|no puedo mas|agotad[ao]|"
    r"se (?:fugo|fue) de (?:la )?casa|no quiere vivir conmigo)\b",
    r"\b(?:al limite con el cuidado|necesito que (?:alguien )?me releve)\b",
    r"\b(?:medicacion|medicamento|dosis|diagnostico|sentencia de (?:mi|nuestro)|"
    r"audiencia de (?:mi|nuestro)|me ordeno el tribunal)\b",
)
IDENTIFICADORES = (
    r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
    r"\b\d{1,2}(?:\.\d{3}){2}-?[\dkK]\b|\b\d{7,8}-[\dkK]\b",
    r"(?<!\w)(?:\+?56[ .-]?)?(?:9[ .-]?)\d{4}[ .-]?\d{4}\b",
    r"\b(?:mi nombre es|me llamo|se llama|su nombre es)\s+[A-ZÁÉÍÓÚÑ]"
    r"[\wáéíóúñ-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ-]+){0,3}",
)


def nivel_riesgo(pregunta: str, contexto: tuple[str, ...] = ()) -> str:
    """Evaluar los turnos disponibles sin emitir un diagnóstico."""
    texto = normalizar(" ".join((*contexto[-4:], pregunta)))
    # Caso distinto de una coincidencia literal con «no responde».
    texto = re.sub(
        r"\bno responde (?:a (?:mis|los) )?(?:mensajes|correos)\b", "", texto
    )
    if any(re.search(patron, texto) for patron in ROJO):
        return "rojo"
    if any(re.search(patron, texto) for patron in AMARILLO):
        return "amarillo"
    return "verde"


def contiene_identificadores(texto: str) -> bool:
    """Detectar patrones comunes. Los textos de casos reales requieren otra política."""
    return any(
        re.search(patron, texto, flags=re.IGNORECASE if i < 3 else 0)
        for i, patron in enumerate(IDENTIFICADORES)
    )


def consulta_contextual(pregunta: str, contexto: tuple[str, ...]) -> str:
    """Añadir un turno previo a preguntas de seguimiento breves."""
    if contexto and re.match(
        r"^(?:y\b|entonces\b|en ese caso\b|pero\b)", normalizar(pregunta).lstrip("¿¡ ")
    ):
        return f"{contexto[-1]}\n{pregunta}"
    return pregunta


def canales_ayuda() -> list[dict]:
    """Servir únicamente canales registrados mediante configuración institucional."""
    ruta = os.getenv("FAE_CANALES_APROBADOS")
    if not ruta:
        return []
    try:
        entradas = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(entradas, list):
        return []
    return [
        {
            "nombre": item["nombre"],
            "telefono": item["telefono"],
            "uso": item.get("uso", ""),
        }
        for item in entradas
        if isinstance(item, dict)
        and isinstance(item.get("nombre"), str)
        and re.fullmatch(r"\+?[\d -]{3,22}", str(item.get("telefono", "")))
    ]
