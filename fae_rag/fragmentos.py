"""Fragmentación reproducible de textos revisados con trazabilidad."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from .archivos import guardar_json
from .catalogo import leer_catalogo
from .configuracion import BASE, SALIDA_URLS
from .taxonomia import CATEGORIAS
from .texto import limpiar_texto


def leer_chunks_suplementarios() -> list[dict]:
    """Leer las fuentes añadidas después del catálogo original de las matrices."""
    carpeta = BASE / "resultados" / "fuentes_suplementarias"
    return [
        item
        for ruta in sorted(carpeta.glob("*.json"))
        for item in json.loads(ruta.read_text(encoding="utf-8"))
    ]


def fragmentar(
    texto: str, tamano: int = 1800, solapamiento: int = 250
) -> Iterator[str]:
    """Ventanas acotadas en caracteres, con solapamiento, sin omitir texto."""
    if tamano <= solapamiento or solapamiento < 0:
        raise ValueError("Tamano debe superar al solapamiento")
    texto = limpiar_texto(texto)
    inicio = 0
    while inicio < len(texto):
        fin = min(inicio + tamano, len(texto))
        yield texto[inicio:fin]
        if fin == len(texto):
            break
        inicio = fin - solapamiento


def crear_chunks(salida: Path = SALIDA_URLS) -> tuple[list[dict], list[dict]]:
    """Preparar solamente textos revisados y listar los pendientes."""
    chunks, pendientes = [], []
    revision_path = salida / "revision_textos.json"
    revisiones = (
        json.loads(revision_path.read_text(encoding="utf-8"))
        if revision_path.exists()
        else {}
    )
    aprobados = salida / "textos_aprobados"
    aprobados.mkdir(parents=True, exist_ok=True)
    for x in leer_catalogo(salida):
        if x.get("duplicado_de"):
            continue
        path = aprobados / (x["url_id"] + ".txt")
        if not path.exists():
            pendientes.append(
                {
                    "url_id": x["url_id"],
                    "motivo": "Falta texto revisado en textos_aprobados",
                }
            )
            continue
        if len(x["categorias"]) != 1:
            pendientes.append(
                {
                    "url_id": x["url_id"],
                    "motivo": "Falta categoria unica; resolver en catalogo_urls.json",
                }
            )
            continue
        cat = x["categorias"][0]
        if cat not in CATEGORIAS:
            raise ValueError("Categoria no valida para " + x["url_id"])
        texto = path.read_text(encoding="utf-8-sig")
        if len(texto.strip()) < 300:
            pendientes.append(
                {
                    "url_id": x["url_id"],
                    "motivo": "Texto aprobado insuficiente (menos de 300 caracteres)",
                }
            )
            continue
        if revisiones and x["url_id"] not in revisiones:
            pendientes.append(
                {
                    "url_id": x["url_id"],
                    "motivo": "Falta registro de revisión con alcance y SHA-256",
                }
            )
            continue
        sha = hashlib.sha256(limpiar_texto(texto).encode()).hexdigest()
        revision = revisiones.get(x["url_id"], {})
        if revision and hashlib.sha256(
            texto.encode("utf-8")
        ).hexdigest() != revision.get("sha256"):
            pendientes.append(
                {
                    "url_id": x["url_id"],
                    "motivo": "Texto aprobado cambió desde su revisión; revisar antes de ingerir",
                }
            )
            continue
        enlace = x.get("url_documento", x["url"])
        for i, parte in enumerate(fragmentar(texto)):
            chunk_id = (
                "web_"
                + hashlib.sha256(f"{x['url_id']}|{sha}|{cat}|{i}".encode()).hexdigest()[
                    :32
                ]
            )
            meta = {
                "chunk_id": chunk_id,
                "categoria": cat,
                "nombre_categoria": CATEGORIAS[cat],
                "seccion": CATEGORIAS[cat],
                "fuente": x["url_id"],
                "enlace": enlace,
                "enlace_matriz": x["url"],
                "titulo": x.get("titulo", ""),
                "url_id": x["url_id"],
                "tipo_contenido": "texto_url_revisado",
                "alcance_texto": revision.get("alcance", "no_declarado"),
                "revision": revision.get("nota", ""),
                "indice_fragmento": i,
                "sha256_texto": sha,
                "referencias": x["referencias"],
                "origenes": x["origenes"],
            }
            contenido = f"[Categoria]: {cat} - {CATEGORIAS[cat]}\n[Fuente URL]: {enlace}\n[Tipo]: {meta['alcance_texto']}\n[Texto]: {parte}"
            chunks.append({"page_content": contenido, "metadata": meta})
    guardar_json(salida / "chunks_urls.json", chunks)
    guardar_json(salida / "textos_pendientes.json", pendientes)
    print(
        f"Chunks de texto revisado: {len(chunks)}. URL pendientes: {len(pendientes)}."
    )
    return chunks, pendientes
