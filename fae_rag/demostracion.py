"""Corpus sintético aislado para demostrar el flujo en Render."""

from contextlib import closing

from .configuracion import parametros_postgres
from .contratos import Documento
from .metricas_demo import ESQUEMA_METRICAS

FUENTES = (
    (
        "ref_demo01",
        "CAT-01",
        "Marco normativo en la demostración",
        "Este ejemplo muestra cómo indicar la vigencia de una orientación FAE. "
        "Una pregunta sobre requisitos o beneficios debe citar la fuente oficial aplicable.",
    ),
    (
        "ref_demo02",
        "CAT-02",
        "Autocuidado en la demostración",
        "Ejemplo ficticio de autocuidado y apoyo para familias de acogida. "
        "El material de demostración organiza dudas sobre cansancio, descanso y redes de apoyo.",
    ),
    (
        "ref_demo03",
        "CAT-03",
        "Preparación del egreso en la demostración",
        "Ejemplo ficticio sobre transición y egreso. La familia reúne preguntas "
        "sobre la despedida, el acompañamiento y la continuidad de vínculos.",
    ),
    (
        "ref_demo04",
        "CAT-04",
        "Ingreso al acogimiento en la demostración",
        "Ejemplo ficticio de preparación. La familia pregunta por postulación, "
        "formación y rutinas de llegada, como sueño, horarios y adaptación.",
    ),
    (
        "ref_demo05",
        "CAT-05",
        "Experiencia del niño en la demostración",
        "Ejemplo ficticio de escucha y participación del niño, niña o adolescente "
        "en una conversación sobre cambios, rutinas y personas importantes.",
    ),
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS public.fae_fuentes_demo (
    id text PRIMARY KEY,
    categoria text NOT NULL,
    titulo text NOT NULL,
    contenido text NOT NULL
);
CREATE INDEX IF NOT EXISTS fae_demo_texto ON public.fae_fuentes_demo USING gin
    (to_tsvector('spanish', titulo || ' ' || contenido));
"""


def preparar_demo() -> None:
    import psycopg2
    from psycopg2.extras import execute_values

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion, conexion.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(749312801)")
            cursor.execute(ESQUEMA)
            cursor.execute(ESQUEMA_METRICAS)
            execute_values(
                cursor,
                """INSERT INTO public.fae_fuentes_demo VALUES %s
                   ON CONFLICT (id) DO UPDATE SET categoria = EXCLUDED.categoria,
                   titulo = EXCLUDED.titulo, contenido = EXCLUDED.contenido""",
                FUENTES,
            )


def buscar_demo(
    pregunta: str, categoria: str | None = None, limite: int = 3
) -> list[Documento]:
    """Recuperar extractos sintéticos mediante coincidencias léxicas."""
    import psycopg2

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                """
                WITH terminos AS (
                    SELECT string_agg(quote_literal(lexema), ' | ') AS expresion
                    FROM unnest(tsvector_to_array(to_tsvector('spanish', %s))) AS lexema
                    WHERE length(lexema) >= 3
                ), consulta AS (
                    SELECT to_tsquery('simple', expresion) AS q FROM terminos
                )
                SELECT id, categoria, titulo, contenido,
                    ts_rank_cd(to_tsvector('spanish', titulo || ' ' || contenido), q) AS rango
                FROM public.fae_fuentes_demo, consulta
                WHERE to_tsvector('spanish', titulo || ' ' || contenido) @@ q
                  AND (%s::text IS NULL OR categoria = %s)
                ORDER BY rango DESC, id LIMIT %s
                """,
                (pregunta, categoria, categoria, max(1, min(10, limite))),
            )
            return [
                {
                    "chunk_id": uid,
                    "categoria": cat,
                    "seccion": cat,
                    "fuente": titulo,
                    "contenido": contenido,
                    "metadata": {
                        "titulo": titulo,
                        "alcance_texto": "documento_sintetico",
                        "recuperacion": "textual_demostracion",
                    },
                    "similitud": float(rango),
                }
                for uid, cat, titulo, contenido, rango in cursor.fetchall()
            ]
