"""Embeddings de Gemini para documentos y consultas, 1536 dimensiones.
Gemini embedding 001: normalización manual requerida al truncar a 1536.
"""

import math
import os
import time

MODELO_EMBEDDING = "gemini-embedding-001"
DIMENSIONES = 1536


def crear_cliente():
    from google import genai

    clave = os.getenv("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta GEMINI_API_KEY en el archivo .env")
    return genai.Client(api_key=clave)


def generar_embedding(
    texto: str, cliente, tipo: str = "RETRIEVAL_DOCUMENT"
) -> list[float]:
    """Generar un solo vector, también utilizado por las consultas."""
    return generar_embeddings([texto], cliente, tipo)[0]


def generar_embeddings(
    textos: list[str], cliente, tipo: str = "RETRIEVAL_DOCUMENT"
) -> list[list[float]]:
    """Generar varios vectores con la misma configuración y normalización."""
    from google.genai import types
    from google.genai.errors import ClientError

    if tipo not in ("RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"):
        raise ValueError("Tipo de tarea no admitido")
    if not textos:
        return []
    config = types.EmbedContentConfig(
        task_type=tipo,
        output_dimensionality=DIMENSIONES,
    )
    for intento in range(12):
        try:
            respuesta = cliente.models.embed_content(
                model=MODELO_EMBEDDING, contents=textos, config=config
            )
            break
        except ClientError as exc:
            if exc.code != 429 or intento == 11:
                raise
            detalles = exc.details if isinstance(exc.details, dict) else {}
            avisos = detalles.get("error", {}).get("details", [])
            espera = 60.0
            cuota_diaria = any(
                "embed_content_free_tier_requests" in violacion.get("quotaMetric", "")
                for aviso in avisos
                for violacion in aviso.get("violations", [])
            )
            for aviso in avisos:
                if aviso.get("@type", "").endswith("RetryInfo"):
                    valor = aviso.get("retryDelay", "")
                    try:
                        espera = max(2.0, float(valor.rstrip("s")) + 2)
                    except (ValueError, AttributeError):
                        pass
                    break
            if cuota_diaria or espera > 300:
                raise RuntimeError(
                    "Cuota diaria de embeddings Gemini agotada; "
                    "la ingesta es reanudable cuando se restablezca la cuota."
                ) from None
            print(f"Cuota temporal de Gemini; reintento en {espera:g} s")
            time.sleep(espera)
    if len(respuesta.embeddings or []) != len(textos):
        raise ValueError("Gemini devolvió una cantidad inesperada de embeddings")
    salida = []
    for embedding in respuesta.embeddings:
        vector = embedding.values
        if len(vector) != DIMENSIONES:
            raise ValueError(
                f"Se esperaban {DIMENSIONES} dimensiones y llegaron {len(vector)}"
            )
        norma = math.sqrt(sum(float(x) * float(x) for x in vector))
        if norma == 0:
            raise ValueError("El embedding generado tiene norma cero")
        salida.append([float(x) / norma for x in vector])
    return salida
