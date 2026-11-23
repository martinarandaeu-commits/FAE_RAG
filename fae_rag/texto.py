"""Limpieza y normalización de datos bibliográficos."""

import re
import unicodedata


def limpiar_texto(valor: object) -> str:
    """Normaliza espacios y saltos de linea sin convertir nulos en texto 'nan'."""
    if valor is None:
        return ""
    if not isinstance(valor, (str, list, dict)):
        import pandas as pd

        if pd.isna(valor):
            return ""
    texto = str(valor)
    texto = re.sub(r"[\r\n\t]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar(texto: object) -> str:
    """Obtener una clave de comparación sin tildes ni espacios repetidos."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", limpiar_texto(texto).lower())
        if unicodedata.category(ch) != "Mn"
    )
