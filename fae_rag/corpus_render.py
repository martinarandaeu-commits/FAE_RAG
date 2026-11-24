"""Cargar el corpus E5 incluido en el despliegue en su propio esquema."""

import gzip
import json
import math
import os
from collections.abc import Iterator
from contextlib import closing
from hashlib import file_digest
from itertools import batched
from pathlib import Path

from .configuracion import BASE, parametros_postgres
from .metricas_demo import ESQUEMA_METRICAS
from .taxonomia import CATEGORIAS

MODELO_CORPUS = "intfloat/multilingual-e5-base"
DIMENSIONES = 768
TABLA_CORPUS = "fae_corpus.vectores"

ESQUEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS fae_corpus;
CREATE TABLE IF NOT EXISTS fae_corpus.vectores (
    chunk_id text PRIMARY KEY,
    categoria_id text NOT NULL,
    seccion text,
    fuente text NOT NULL,
    page_content text NOT NULL,
    metadata_json jsonb NOT NULL,
    embedding vector(768) NOT NULL
);
CREATE TABLE IF NOT EXISTS fae_corpus.version (
    id boolean PRIMARY KEY CHECK (id),
    sha256 text NOT NULL,
    vectores integer NOT NULL CHECK (vectores > 0)
);
"""

INDICES = """
CREATE INDEX IF NOT EXISTS fae_corpus_hnsw ON fae_corpus.vectores
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS fae_corpus_gin ON fae_corpus.vectores
    USING gin (to_tsvector('spanish', page_content));
"""


def archivo_corpus() -> Path | None:
    """Resolver la ruta configurada para el despliegue documental de prueba."""
    ruta = os.getenv("FAE_CORPUS_JSON")
    return BASE / ruta if ruta and os.getenv("FAE_MODO") == "demo" else None


def registros(ruta: Path) -> Iterator[tuple]:
    import ijson
    from psycopg2.extras import Json

    abrir = gzip.open if ruta.suffix == ".gz" else open
    with abrir(ruta, "rb") as archivo:
        for fila in ijson.items(archivo, "registros.item", use_float=True):
            identificador = fila["chunk_id"]
            categoria = fila["categoria_id"]
            contenido = fila["page_content"]
            metadata = fila["metadata"]
            vector = fila["embedding"]
            if (
                not identificador
                or categoria not in CATEGORIAS
                or not contenido.strip()
                or metadata.get("modelo_embedding") != MODELO_CORPUS
                or len(vector) != DIMENSIONES
                or not all(math.isfinite(valor) for valor in vector)
                or not any(vector)
            ):
                raise ValueError(f"Registro incompatible con E5: {identificador}")
            yield (
                identificador,
                categoria,
                fila["seccion"],
                fila["fuente"],
                contenido,
                Json(metadata),
                json.dumps(vector, separators=(",", ":"), allow_nan=False),
            )


def cargar_corpus(ruta: Path) -> int:
    """Instalar una versión completa o reutilizar la que ya está indexada."""
    import psycopg2
    from psycopg2.extras import execute_values

    with ruta.open("rb") as archivo:
        huella = file_digest(archivo, "sha256").hexdigest()
    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion, conexion.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(749312803)")
            cursor.execute(ESQUEMA)
            cursor.execute(ESQUEMA_METRICAS)
            cursor.execute("SELECT sha256, vectores FROM fae_corpus.version WHERE id")
            version = cursor.fetchone()
            if version and version[0] == huella:
                cursor.execute("SELECT count(*) FROM fae_corpus.vectores")
                if cursor.fetchone()[0] == version[1]:
                    cursor.execute(INDICES)
                    return version[1]

            cursor.execute("TRUNCATE fae_corpus.vectores")
            total = 0
            for lote in batched(registros(ruta), 96):
                execute_values(
                    cursor,
                    """INSERT INTO fae_corpus.vectores
                       (chunk_id, categoria_id, seccion, fuente, page_content,
                        metadata_json, embedding) VALUES %s""",
                    lote,
                    page_size=len(lote),
                )
                total += len(lote)
            if not total:
                raise ValueError("El archivo configurado no contiene vectores.")

            cursor.execute(INDICES)
            cursor.execute("ANALYZE fae_corpus.vectores")
            cursor.execute(
                """INSERT INTO fae_corpus.version VALUES (true, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET sha256 = EXCLUDED.sha256,
                       vectores = EXCLUDED.vectores""",
                (huella, total),
            )
            return total
