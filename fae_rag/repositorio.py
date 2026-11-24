"""Adaptador PostgreSQL/pgvector para ingesta idempotente."""

import json
import os
import time

from .configuracion import cargar_entorno, parametros_postgres


def insertar_vectores(chunks: list[dict]) -> None:
    """Se ejecuta solo bajo --modo insertar, con variables de entorno definidas."""
    cargar_entorno()
    import psycopg2
    from psycopg2.extras import Json

    from .embeddings import (
        MODELO_EMBEDDING,
        crear_cliente,
        generar_embedding,
        generar_embeddings,
    )

    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "Define GEMINI_API_KEY en .env; nunca escribas claves en el código."
        )
    if not os.getenv("PGPASSWORD"):
        raise RuntimeError("Define PGPASSWORD para conectar PostgreSQL.")
    tamano_lote = int(os.getenv("GEMINI_TAMANO_LOTE", "8"))
    pausa_lotes = float(os.getenv("GEMINI_PAUSA_LOTES", "8"))
    if not 1 <= tamano_lote <= 100 or pausa_lotes < 0:
        raise ValueError("GEMINI_TAMANO_LOTE debe ser 1..100 y GEMINI_PAUSA_LOTES >= 0")
    conn = psycopg2.connect(**parametros_postgres())
    nuevos = existentes = 0
    cliente = None
    try:
        cliente = crear_cliente()
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", ("public.vectores_rag_fae",))
            if cur.fetchone()[0] is None:
                raise RuntimeError(
                    "Falta la tabla vectores_rag_fae: ejecuta python preparar_bd.py --modo esquema"
                )
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='ux_vectores_rag_fae_chunk_id')"
            )
            if not cur.fetchone()[0]:
                raise RuntimeError(
                    "Falta el indice unico: ejecuta python preparar_bd.py --modo esquema"
                )
            conn.commit()
            pendientes = []
            for item in chunks:
                meta = item["metadata"]
                cur.execute(
                    """SELECT 1 FROM public.vectores_rag_fae
                        WHERE chunk_id=%s AND embedding IS NOT NULL
                        AND metadata_json->>'modelo_embedding'=%s
                        AND page_content=%s AND categoria_id=%s LIMIT 1""",
                    (
                        meta["chunk_id"],
                        MODELO_EMBEDDING,
                        item["page_content"],
                        meta["categoria"],
                    ),
                )
                if cur.fetchone():
                    existentes += 1
                else:
                    pendientes.append(item)
            conn.commit()
            print(f"Por vectorizar: {len(pendientes)}; ya existentes: {existentes}")
            for inicio in range(0, len(pendientes), tamano_lote):
                lote = pendientes[inicio : inicio + tamano_lote]
                textos = [item["page_content"] for item in lote]
                vectores = (
                    [generar_embedding(textos[0], cliente, "RETRIEVAL_DOCUMENT")]
                    if len(lote) == 1
                    else generar_embeddings(textos, cliente, "RETRIEVAL_DOCUMENT")
                )
                for item, vector in zip(lote, vectores, strict=True):
                    meta = item["metadata"]
                    meta = {
                        **meta,
                        "modelo_embedding": MODELO_EMBEDDING,
                        "dimensiones_embedding": 1536,
                    }
                    try:
                        cur.execute(
                            """INSERT INTO public.vectores_rag_fae
                        (chunk_id, categoria_id, seccion, fuente, page_content, metadata_json, embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                        categoria_id=EXCLUDED.categoria_id, seccion=EXCLUDED.seccion,
                        fuente=EXCLUDED.fuente, page_content=EXCLUDED.page_content,
                        metadata_json=EXCLUDED.metadata_json, embedding=EXCLUDED.embedding""",
                            (
                                meta["chunk_id"],
                                meta["categoria"],
                                meta["seccion"],
                                meta["fuente"],
                                item["page_content"],
                                Json(meta),
                                json.dumps(vector),
                            ),
                        )
                        nuevos += cur.rowcount
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                print(f"Vectorizados {nuevos}/{len(pendientes)} pendientes")
                if pausa_lotes and inicio + len(lote) < len(pendientes):
                    time.sleep(pausa_lotes)
        print(f"Ingesta completada. Nuevos: {nuevos}; existentes: {existentes}")
    finally:
        conn.close()
        if cliente is not None:
            cliente.close()
