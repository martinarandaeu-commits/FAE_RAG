"""Entradas de consola: orquestación sin lógica de negocio duplicada."""

import argparse
import json
from collections import Counter

from .catalogo import preparar
from .configuracion import ARCHIVO, BASE
from .extraccion import descargar
from .fragmentos import crear_chunks
from .matrices import procesar_matrices_rag
from .repositorio import insertar_vectores


def main_referencias() -> None:
    """Validar o insertar las referencias de la matriz principal."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--modo", choices=["validar", "insertar"], default="validar")
    args = parser.parse_args()
    if not ARCHIVO.exists():
        raise FileNotFoundError(f"No se encuentra la matriz Excel: {ARCHIVO}")
    chunks, pendientes = procesar_matrices_rag()
    out = BASE / "resultados"
    out.mkdir(exist_ok=True)
    (out / "chunks_validacion.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "revision_manual.json").write_text(
        json.dumps(pendientes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Total de chunks:", len(chunks))
    print(
        "Por categoria:",
        dict(sorted(Counter(x["metadata"]["categoria"] for x in chunks).items())),
    )
    print("Pendientes de revision:", len(pendientes))
    print(
        "Ejemplo de chunk:\n",
        chunks[0]["page_content"][:900] if chunks else "(ninguno)",
    )
    print("Archivos de validacion:", out)
    if args.modo == "insertar":
        if pendientes:
            print(
                f"ATENCION: {len(pendientes)} filas ambiguas omitidas; revisar resultados/revision_manual.json"
            )
        insertar_vectores(chunks)
        print("Ingesta finalizada.")


def main_urls() -> None:
    """Coordinar las etapas de preparación, descarga y vectorización de URL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modo",
        choices=("preparar", "descargar", "chunks", "insertar"),
        default="preparar",
    )
    parser.add_argument(
        "--limite", type=int, default=0, help="Limite de descargas; 0 = todas"
    )
    parser.add_argument(
        "--url-id",
        action="append",
        help="Descargar solo este ID; repetir si hace falta",
    )
    args = parser.parse_args()
    if args.limite < 0:
        parser.error("--limite no puede ser negativo")
    if args.modo == "preparar":
        preparar()
    elif args.modo == "descargar":
        descargar(args.limite, solo_ids=set(args.url_id) if args.url_id else None)
    else:
        chunks, pendientes = crear_chunks()
        if args.modo == "insertar":
            if not chunks:
                raise RuntimeError(
                    "No hay texto revisado para vectorizar. Revisa textos_pendientes.json."
                )
            print(
                f"Solo se insertaran textos aprobados; quedan {len(pendientes)} URL pendientes."
            )
            insertar_vectores(chunks)
