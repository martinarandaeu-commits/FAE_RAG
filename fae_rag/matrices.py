"""Lectura de matrices y construcción de referencias bibliográficas."""

import hashlib
from pathlib import Path

import pandas as pd

from .configuracion import ARCHIVO, HOJAS
from .taxonomia import CATEGORIAS, categoria_por_contexto
from .texto import limpiar_texto, normalizar


def construir_chunk(datos: dict, categoria: str, fuente: str, hoja: str) -> str:
    """Construir el texto bibliográfico manteniendo el formato existente."""
    campos = [
        ("Referencia Bibliografica", "Referencia/Título"),
        ("Autor e Institucion", "Autor/Institución"),
        ("Año", "Año"),
        ("Pais", "País"),
        ("Seccion Taxonomica", "Sección"),
        ("Objetivo o Aporte", "Objetivo/Aporte"),
        ("Hallazgos y Bienestar", "Hallazgos / aporte al bienestar"),
        ("Recomendaciones Practicas FAE", "Recomendaciones para FAE"),
        ("Enlace de Verificacion", "Enlace comprobado"),
    ]
    lines = [
        f"[Categoria]: {categoria} - {CATEGORIAS[categoria]}",
        f"[Fuente]: {fuente}",
        f"[Hoja]: {hoja}",
    ]
    for label, col in campos:
        value = limpiar_texto(datos.get(col, ""))
        if value:
            lines.append(f"[{label}]: {value}")
    return "\n".join(lines)


def procesar_matrices_rag(
    ruta_excel: Path = ARCHIVO,
) -> tuple[list[dict], list[dict]]:
    """Leer las hojas de la matriz, clasificar y deduplicar las referencias."""
    xls = pd.ExcelFile(ruta_excel)
    fuente = Path(ruta_excel).name
    chunks, pendientes = [], []
    huellas = set()
    for hoja in HOJAS:
        if hoja not in xls.sheet_names:
            xls.close()
            raise ValueError(f"Falta la hoja requerida: {hoja}")
        df = pd.read_excel(xls, sheet_name=hoja, dtype=str).fillna("")
        for idx, row in df.iterrows():
            d = {str(k): limpiar_texto(v) for k, v in row.to_dict().items()}
            if hoja == "Matriz completa":
                d = {
                    **d,
                    "Sección": "Autocuidado y Bienestar del Cuidador",
                    "Referencia/Título": d.get("Título", ""),
                    "Autor/Institución": d.get("Autor", ""),
                    "Objetivo/Aporte": d.get("Objetivo", ""),
                    "Hallazgos / aporte al bienestar": d.get(
                        "Hallazgos sobre autocuidado/bienestar", ""
                    ),
                }
            elif hoja == "Orientaciones preacogimiento":
                d = {
                    **d,
                    "Sección": "Preparación previa y formación",
                    "Referencia/Título": d.get(
                        "Orientación clave previa al acogimiento", ""
                    ),
                    "Autor/Institución": "Orientaciones preacogimiento FAE",
                    "Objetivo/Aporte": d.get("Qué debe hacer el equipo FAE", ""),
                    "Hallazgos / aporte al bienestar": d.get(
                        "Qué debe conocer/preparar la familia", ""
                    ),
                    "Recomendaciones para FAE": d.get("Fundamento USS", ""),
                }
            titulo = d.get("Referencia/Título", "")
            if not titulo:
                continue
            cat, razon = categoria_por_contexto(d.get("Sección", ""), titulo, hoja)
            if not cat:
                pendientes.append(
                    {
                        "hoja": hoja,
                        "fila_excel": idx + 2,
                        "titulo": titulo,
                        "motivo": razon,
                    }
                )
                continue
            # Los duplicados bibliograficos se detectan por titulo normalizado y ano.
            clave = hashlib.sha256(
                (normalizar(titulo) + "|" + d.get("Año", "")).encode("utf-8")
            ).hexdigest()
            if clave in huellas:
                continue
            huellas.add(clave)
            chunk_id = "ref_" + clave[:24]
            metadata = {
                "chunk_id": chunk_id,
                "categoria": cat,
                "nombre_categoria": CATEGORIAS[cat],
                "seccion": d.get("Sección", ""),
                "autor": d.get("Autor/Institución", ""),
                "anio": d.get("Año", ""),
                "pais": d.get("País", ""),
                "fuente": fuente,
                "hoja": hoja,
                "fila_excel": idx + 2,
                "criterio_clasificacion": razon,
                "enlace": d.get("Enlace comprobado", ""),
            }
            chunks.append(
                {
                    "page_content": construir_chunk(d, cat, fuente, hoja),
                    "metadata": metadata,
                }
            )
    xls.close()
    return chunks, pendientes
