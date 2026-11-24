"""Recuperación híbrida: similitud coseno y texto completo con fusión RRF."""

import json
import os

from .configuracion import cargar_entorno, parametros_postgres
from .contratos import Documento
from .embeddings import MODELO_EMBEDDING, crear_cliente, generar_embedding
from .taxonomia import CATEGORIAS

CONSULTA_HIBRIDA = """
WITH candidatos_semanticos AS (
    SELECT chunk_id, embedding <=> %(vector)s::vector AS distancia
    FROM public.vectores_rag_fae
    WHERE embedding IS NOT NULL
      AND metadata_json->>'modelo_embedding' = %(modelo)s
      AND (%(categoria)s::text IS NULL OR categoria_id = %(categoria)s)
    ORDER BY embedding <=> %(vector)s::vector
    LIMIT %(candidatos)s
), semanticos AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (ORDER BY distancia, chunk_id) AS puesto
    FROM candidatos_semanticos
), candidatos_lexicos AS (
    SELECT chunk_id,
           ts_rank_cd(to_tsvector('spanish', page_content),
                      plainto_tsquery('spanish', %(pregunta)s)) AS relevancia
    FROM public.vectores_rag_fae
    WHERE to_tsvector('spanish', page_content)
          @@ plainto_tsquery('spanish', %(pregunta)s)
      AND embedding IS NOT NULL
      AND metadata_json->>'modelo_embedding' = %(modelo)s
      AND (%(categoria)s::text IS NULL OR categoria_id = %(categoria)s)
    ORDER BY relevancia DESC, chunk_id
    LIMIT %(candidatos)s
), lexicos AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (ORDER BY relevancia DESC, chunk_id) AS puesto
    FROM candidatos_lexicos
), fusionados AS (
    SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
           COALESCE(1.0 / (60 + s.puesto), 0)
           + COALESCE(1.0 / (60 + l.puesto), 0) AS puntuacion
    FROM semanticos s FULL OUTER JOIN lexicos l USING (chunk_id)
)
SELECT v.chunk_id, v.categoria_id, v.seccion, v.fuente,
       v.page_content, v.metadata_json,
       1 - (v.embedding <=> %(vector)s::vector) AS similitud,
       f.puntuacion
FROM fusionados f JOIN public.vectores_rag_fae v USING (chunk_id)
ORDER BY f.puntuacion DESC,
    CASE v.metadata_json->>'prioridad'
        WHEN '1' THEN 1 WHEN '2' THEN 2 WHEN '3' THEN 3 WHEN '4' THEN 4 ELSE 5
    END, v.chunk_id
LIMIT %(limite)s
"""


def buscar(
    pregunta: str,
    categoria: str | None = None,
    limite: int = 3,
    *,
    corpus_render: bool = False,
) -> list[Documento]:
    """Combinar dos rankings sin sumar escalas de relevancia incompatibles."""
    if not pregunta or not pregunta.strip():
        raise ValueError("La pregunta no puede estar vacía.")
    if categoria and categoria not in CATEGORIAS:
        raise ValueError(f"Categoría inválida: {categoria}")
    limite = max(1, min(10, int(limite)))
    cargar_entorno()
    backend = os.getenv("RAG_EMBEDDING_BACKEND", "gemini").lower()
    if corpus_render:
        from .corpus_render import MODELO_CORPUS, TABLA_CORPUS
        from .embeddings_render import crear_cliente as crear_render
        from .embeddings_render import generar_embedding as generar_render

        crear = crear_render
        vectorizar = generar_render
        modelo = MODELO_CORPUS
        consulta = CONSULTA_HIBRIDA.replace("public.vectores_rag_fae", TABLA_CORPUS)
    elif backend == "gemini":
        crear = crear_cliente
        vectorizar = generar_embedding
        modelo = MODELO_EMBEDDING
        consulta = CONSULTA_HIBRIDA
    elif backend == "local":
        from .embeddings_locales import MODELO_EMBEDDING as MODELO_LOCAL
        from .embeddings_locales import crear_cliente as crear_local
        from .embeddings_locales import generar_embedding as generar_local

        crear = crear_local
        vectorizar = generar_local
        modelo = MODELO_LOCAL
        consulta = CONSULTA_HIBRIDA.replace(
            "public.vectores_rag_fae", "public.vectores_rag_fae_local"
        )
    else:
        raise ValueError("RAG_EMBEDDING_BACKEND debe ser gemini o local")
    cliente = crear()
    try:
        vector = vectorizar(pregunta, cliente, "RETRIEVAL_QUERY")
    finally:
        if backend == "gemini" and not corpus_render:
            cliente.close()

    import psycopg2

    conexion = psycopg2.connect(**parametros_postgres())
    try:
        with conexion.cursor() as cursor:
            cursor.execute(
                consulta,
                {
                    "vector": json.dumps(vector),
                    "modelo": modelo,
                    "categoria": categoria,
                    "pregunta": pregunta,
                    "candidatos": max(20, limite * 4),
                    "limite": limite,
                },
            )
            filas = cursor.fetchall()
        return [
            {
                "chunk_id": f[0],
                "categoria": f[1],
                "seccion": f[2],
                "fuente": f[3],
                "contenido": f[4],
                "metadata": {
                    **(f[5] or {}),
                    "recuperacion": "vectorial_textual_rrf",
                    "puntuacion_rrf": float(f[7]),
                },
                "similitud": round(float(f[6]), 4),
            }
            for f in filas
        ]
    finally:
        conexion.close()
