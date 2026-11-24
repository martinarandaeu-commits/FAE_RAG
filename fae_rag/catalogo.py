"""Inventario, trazabilidad y categorización de las URL de los Excel."""

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import openpyxl

from .archivos import guardar_json
from .configuracion import BASE, SALIDA_URLS
from .matrices import procesar_matrices_rag
from .taxonomia import CATEGORIAS
from .texto import limpiar_texto, normalizar


def url_canonica(url: str | None) -> str:
    """Eliminar rastreo sin perder los parámetros que identifican documentos."""
    url = str(url or "").strip()
    if url.startswith("10."):
        url = "https://doi.org/" + url
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Se requiere una URL HTTP(S) o un DOI")
    # Conserva parámetros de identidad (idNorma, pid, q, etc.).
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")
    ]
    return urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path, urlencode(query), "")
    )


def tipo_url(url: str) -> str:
    """Distinguir documentos, fichas y enlaces de localización."""
    p = urlsplit(url)
    host, path = p.hostname.lower(), p.path.lower().rstrip("/")
    if host == "scholar.google.com" or path.endswith("/search"):
        return "busqueda_academica"
    if path.endswith(("/repositorio/resoluciones", "/colaboradores/marco-tecnico")):
        return "repositorio_general"
    if host in ("doi.org", "dx.doi.org"):
        return "doi"
    if path.endswith(".pdf"):
        return "pdf_directo"
    return "pagina_o_ficha"


def leer_catalogo(salida: Path = SALIDA_URLS) -> list[dict]:
    """Leer la matriz y aplicar hallazgos documentales sin perder la URL original."""
    path = salida / "catalogo_urls.json"
    if not path.exists():
        raise RuntimeError("Primero ejecuta --modo preparar")
    items = json.loads(path.read_text(encoding="utf-8"))
    revisiones_path = salida / "enlaces_especificos.json"
    if not revisiones_path.exists():
        return items
    revisiones = json.loads(revisiones_path.read_text(encoding="utf-8"))
    for item in items:
        revision = revisiones.get(item["url_id"])
        if not revision:
            continue
        item["url_documento"] = revision["url_documento"]
        item["estado_localizacion"] = revision["estado_localizacion"]
        if "extractor_pdf" in revision:
            item["extractor_pdf"] = revision["extractor_pdf"]
        if "duplicado_de" in revision:
            item["duplicado_de"] = revision["duplicado_de"]
        if "categoria_principal" in revision:
            categoria = revision["categoria_principal"]
            if categoria not in item["categorias"]:
                raise ValueError(f"Categoría ajena a la matriz: {item['url_id']}")
            item["categorias_matriz"] = item["categorias"]
            item["categorias"] = [categoria]
    return items


def preparar(salida: Path = SALIDA_URLS) -> dict:
    """Preparar el catálogo y sus evidencias sin red ni base de datos."""
    chunks, pendientes = procesar_matrices_rag()
    por_url, por_titulo = {}, {}
    for chunk in chunks:
        m = chunk["metadata"]
        titulo = re.search(
            r"^\[Referencia Bibliografica\]: (.+)$", chunk["page_content"], re.M
        )
        if titulo:
            por_titulo[normalizar(titulo.group(1))] = m
        if m.get("enlace"):
            por_url.setdefault(url_canonica(m["enlace"]), []).append(m)
    catalogo, fuentes, incidencias, filas_con_url = {}, [], [], 0
    for path in sorted((BASE / "data").glob("*.xlsx")):
        fuente = {
            "archivo": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "hojas": [],
        }
        wb = openpyxl.load_workbook(path, data_only=False)
        try:
            for ws in wb:
                fuente["hojas"].append({"nombre": ws.title, "filas": ws.max_row})
                headers = {
                    normalizar(c.value): i for i, c in enumerate(ws[1]) if c.value
                }
                url_idx = next(
                    (
                        headers[h]
                        for h in ("enlace comprobado", "url / doi")
                        if h in headers
                    ),
                    None,
                )
                if url_idx is None:
                    continue
                titulo_idx = next(
                    (
                        headers[h]
                        for h in (
                            "referencia/titulo",
                            "referencia bibliografica",
                            "titulo",
                        )
                        if h in headers
                    ),
                    None,
                )
                for row in ws.iter_rows(min_row=2):
                    celda = row[url_idx]
                    enlace = celda.hyperlink.target if celda.hyperlink else celda.value
                    if not enlace:
                        continue
                    filas_con_url += 1
                    origen = {
                        "archivo": path.name,
                        "hoja": ws.title,
                        "fila_excel": celda.row,
                        "celda_url": celda.coordinate,
                    }
                    titulo = (
                        limpiar_texto(row[titulo_idx].value)
                        if titulo_idx is not None
                        else ""
                    )
                    try:
                        url = url_canonica(enlace)
                    except ValueError as e:
                        incidencias.append(
                            {**origen, "url": str(enlace), "motivo": str(e)}
                        )
                        continue
                    metas = por_url.get(url, []) or (
                        [por_titulo[normalizar(titulo)]]
                        if normalizar(titulo) in por_titulo
                        else []
                    )
                    item = catalogo.setdefault(
                        url,
                        {
                            "url_id": "url_"
                            + hashlib.sha256(url.encode()).hexdigest()[:24],
                            "url": url,
                            "tipo_enlace": tipo_url(url),
                            "categorias": [],
                            "referencias": [],
                            "origenes": [],
                            "verificacion_web": "no realizada",
                            "estado_texto": "pendiente de descarga y revision",
                        },
                    )
                    item["origenes"].append(origen)
                    for m in metas:
                        if m["categoria"] not in item["categorias"]:
                            item["categorias"].append(m["categoria"])
                        if m["chunk_id"] not in item["referencias"]:
                            item["referencias"].append(m["chunk_id"])
                    if titulo and "titulo" not in item:
                        item["titulo"] = titulo
                    if not metas:
                        incidencias.append(
                            {
                                **origen,
                                "url": url,
                                "titulo": titulo,
                                "motivo": "Referencia no cubierta por la matriz principal; requiere clasificacion",
                            }
                        )
        finally:
            wb.close()
        fuentes.append(fuente)
    items = sorted(catalogo.values(), key=lambda x: x["url_id"])
    for item in items:
        item["categorias"].sort()
    guardar_json(salida / "catalogo_urls.json", items)
    items_revisados = leer_catalogo(salida)
    guardar_json(salida / "chunks_bibliograficos.json", chunks)
    guardar_json(salida / "revision_manual.json", pendientes + incidencias)
    informe = {
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "archivos": fuentes,
        "referencias_bibliograficas": len(chunks),
        "referencias_por_categoria": dict(
            sorted(Counter(x["metadata"]["categoria"] for x in chunks).items())
        ),
        "filas_con_url_incluyendo_repetidas": filas_con_url,
        "urls_unicas": len(items),
        "urls_por_tipo": dict(Counter(x["tipo_enlace"] for x in items)),
        "urls_con_varias_categorias": sum(len(x["categorias"]) > 1 for x in items),
        "pendientes_clasificacion": len(pendientes + incidencias),
        "advertencia": "Clasificacion basada en las matrices locales. No acredita acceso al texto completo ni vigencia de normas.",
    }
    guardar_json(salida / "informe_preparacion.json", informe)
    with (salida / "urls_categorizadas.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            [
                "URL ID",
                "Titulo",
                "URL matriz",
                "URL documento localizado",
                "Categorias",
                "Categorias en matrices",
                "Nombres categorias",
                "Tipo enlace",
                "Referencias",
                "Origenes",
                "Verificacion web",
            ]
        )
        for x in items_revisados:
            values = [
                x["url_id"],
                x.get("titulo", ""),
                x["url"],
                x.get("url_documento", ""),
                ", ".join(x["categorias"]),
                ", ".join(x.get("categorias_matriz", x["categorias"])),
                ", ".join(CATEGORIAS[c] for c in x["categorias"]),
                x["tipo_enlace"],
                ", ".join(x["referencias"]),
                " / ".join(
                    f"{o['archivo']} [{o['hoja']}!{o['celda_url']}]"
                    for o in x["origenes"]
                ),
                x["verificacion_web"],
            ]
            writer.writerow(
                [
                    "'" + v if str(v).startswith(("=", "+", "-", "@")) else v
                    for v in values
                ]
            )
    print(
        json.dumps(
            {k: v for k, v in informe.items() if k != "archivos"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return informe
