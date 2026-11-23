"""Contadores anónimos de demostración, sin preguntas ni historiales."""

import secrets
from contextlib import closing

from .configuracion import parametros_postgres

ESQUEMA_METRICAS = """
CREATE TABLE IF NOT EXISTS public.fae_metricas_demo (
    semana date NOT NULL,
    nivel text NOT NULL,
    modo text NOT NULL,
    cantidad integer NOT NULL DEFAULT 0,
    PRIMARY KEY (semana, nivel, modo)
);
CREATE TABLE IF NOT EXISTS public.fae_evaluaciones_demo (
    semana date NOT NULL,
    util boolean NOT NULL,
    cantidad integer NOT NULL DEFAULT 0,
    PRIMARY KEY (semana, util)
);
"""


def registrar_consulta(nivel: str, modo: str) -> None:
    """Añadir solamente el resultado operativo de la consulta."""
    import psycopg2

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion, conexion.cursor() as cursor:
            cursor.execute(
                """INSERT INTO public.fae_metricas_demo VALUES
                       (date_trunc('week', timezone('America/Santiago', now()))::date, %s, %s, 1)
                   ON CONFLICT (semana, nivel, modo) DO UPDATE
                       SET cantidad = fae_metricas_demo.cantidad + 1""",
                (nivel, modo),
            )


def registrar_evaluacion(util: bool) -> None:
    import psycopg2

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion, conexion.cursor() as cursor:
            cursor.execute(
                """INSERT INTO public.fae_evaluaciones_demo VALUES
                       (date_trunc('week', timezone('America/Santiago', now()))::date, %s, 1)
                   ON CONFLICT (semana, util) DO UPDATE
                       SET cantidad = fae_evaluaciones_demo.cantidad + 1""",
                (util,),
            )


def acceso_configurado(clave: str, presentada: str) -> bool:
    return bool(clave) and secrets.compare_digest(clave.encode(), presentada.encode())


def leer_metricas() -> dict[str, list[dict]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT semana, nivel, modo, cantidad FROM public.fae_metricas_demo
                   WHERE cantidad >= 5 ORDER BY semana DESC, nivel, modo LIMIT 500"""
            )
            consultas = list(cursor.fetchall())
            cursor.execute(
                """SELECT semana, util, cantidad FROM public.fae_evaluaciones_demo
                   WHERE cantidad >= 5 ORDER BY semana DESC, util LIMIT 100"""
            )
            return {"consultas": consultas, "evaluaciones": list(cursor.fetchall())}
