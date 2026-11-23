"""Persistencia del portal FAE. Los índices originales viven en public."""

from contextlib import closing, contextmanager

from .configuracion import parametros_postgres

ESQUEMA_PORTAL = """
CREATE SCHEMA IF NOT EXISTS fae_portal;
CREATE TABLE IF NOT EXISTS fae_portal.duplas (
    id uuid PRIMARY KEY, programa text NOT NULL, region text NOT NULL,
    contacto jsonb NOT NULL DEFAULT '{}', publica boolean NOT NULL DEFAULT false,
    activa boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS fae_portal.usuarios (
    id uuid PRIMARY KEY, correo text NOT NULL UNIQUE, clave text NOT NULL,
    rol text NOT NULL CHECK (rol IN ('familia','dupla','curador','admin')),
    dupla uuid REFERENCES fae_portal.duplas ON DELETE SET NULL,
    verificado boolean NOT NULL DEFAULT false, activo boolean NOT NULL DEFAULT true,
    perfil jsonb NOT NULL DEFAULT '{}',
    consentimiento text, consentido_en timestamptz,
    totp bytea, ultimo_totp bigint NOT NULL DEFAULT -1,
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS fae_portal.invitaciones (
    id uuid PRIMARY KEY, huella text NOT NULL UNIQUE,
    dupla uuid REFERENCES fae_portal.duplas ON DELETE CASCADE,
    rol text NOT NULL CHECK (rol IN ('familia','dupla','curador','admin')),
    etiqueta text NOT NULL DEFAULT '', correo text,
    caduca timestamptz NOT NULL, usada_en timestamptz,
    usada_por uuid REFERENCES fae_portal.usuarios ON DELETE SET NULL,
    revocada boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS fae_portal.tokens (
    huella text PRIMARY KEY, usuario uuid NOT NULL REFERENCES fae_portal.usuarios ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('verificar','restablecer','alta_mfa')),
    secreto bytea, caduca timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS fae_portal.sesiones (
    huella text PRIMARY KEY, usuario uuid NOT NULL REFERENCES fae_portal.usuarios ON DELETE CASCADE,
    vista timestamptz NOT NULL DEFAULT now(), caduca timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS fae_portal.turnos (
    id uuid PRIMARY KEY, usuario uuid NOT NULL REFERENCES fae_portal.usuarios ON DELETE CASCADE,
    creado_en timestamptz NOT NULL DEFAULT now(), datos bytea NOT NULL
);
CREATE INDEX IF NOT EXISTS fae_turnos_titular ON fae_portal.turnos (usuario, creado_en DESC);
CREATE INDEX IF NOT EXISTS fae_turnos_fecha ON fae_portal.turnos (creado_en);
CREATE TABLE IF NOT EXISTS fae_portal.auditoria (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor uuid, accion text NOT NULL, objeto text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS fae_portal.limites (
    huella text PRIMARY KEY, vence timestamptz NOT NULL, cantidad integer NOT NULL
);
CREATE TABLE IF NOT EXISTS fae_portal.configuracion (
    clave text PRIMARY KEY, valor jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS fae_portal.canales (
    id uuid PRIMARY KEY, nombre text NOT NULL, telefono text NOT NULL,
    uso text NOT NULL, region text, orden integer NOT NULL, aprobado boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS fae_portal.recursos (
    id uuid PRIMARY KEY, serie text NOT NULL, clase text NOT NULL,
    categoria text NOT NULL, titulo text NOT NULL, descripcion text NOT NULL,
    enlace text, licencia text NOT NULL, vigencia text NOT NULL,
    autor text NOT NULL DEFAULT '', anio integer, prioridad integer NOT NULL DEFAULT 5,
    estado text NOT NULL, creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS fae_recurso_activo
    ON fae_portal.recursos (serie) WHERE estado = 'publicado';
ALTER TABLE fae_portal.recursos ADD COLUMN IF NOT EXISTS ubicacion jsonb;
CREATE INDEX IF NOT EXISTS fae_recurso_texto ON fae_portal.recursos USING gin
    (to_tsvector('spanish', titulo || ' ' || descripcion));
"""


@contextmanager
def transaccion():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    with closing(psycopg2.connect(**parametros_postgres())) as conexion:
        with conexion, conexion.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '6s'")
            yield cur


def preparar_portal() -> None:
    with transaccion() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(749312802)")
        cur.execute(ESQUEMA_PORTAL)


def auditar(cur, actor: str | None, accion: str, objeto: str) -> None:
    cur.execute(
        "INSERT INTO fae_portal.auditoria(actor, accion, objeto) VALUES (%s, %s, %s)",
        (actor, accion, objeto),
    )


def ajuste(cur, clave: str, defecto):
    cur.execute("SELECT valor FROM fae_portal.configuracion WHERE clave=%s", (clave,))
    fila = cur.fetchone()
    return fila["valor"] if fila else defecto


def purgar_vencidos() -> None:
    with transaccion() as cur:
        dias = ajuste(cur, "retencion_dias", 90)
        cur.execute(
            "DELETE FROM fae_portal.turnos WHERE creado_en <= now()-(%s * interval '1 day')",
            (dias,),
        )
        for sentencia in (
            "DELETE FROM fae_portal.tokens WHERE caduca <= now()",
            "DELETE FROM fae_portal.sesiones WHERE caduca <= now()",
            "DELETE FROM fae_portal.limites WHERE vence <= now()",
        ):
            cur.execute(sentencia)
