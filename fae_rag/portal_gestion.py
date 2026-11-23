"""Backoffice FAE con permisos explícitos por operación."""

import secrets
from base64 import b64decode
from binascii import Error as CodigoInvalido
from datetime import timedelta
from io import BytesIO
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import Json
from pydantic import BaseModel, Field

from .metricas_demo import leer_metricas
from .portal_auth import correo_normalizado, huella, titular, utc
from .portal_db import ajuste, auditar, transaccion


class Contacto(BaseModel):
    psicologia: str = Field(default="", max_length=70)
    trabajo_social: str = Field(default="", max_length=70)
    telefono: str = Field(default="", pattern=r"^(?:\+?[0-9 -]{3,22})?$")
    correo: str = Field(default="", max_length=254)
    horario: str = Field(default="", max_length=150)
    emergencia: str = Field(default="", max_length=150)


class Dupla(BaseModel):
    programa: str = Field(min_length=2, max_length=150)
    region: str = Field(min_length=2, max_length=80)
    contacto: Contacto = Field(default_factory=Contacto)
    publica: bool = False
    activa: bool = True


class ContactoDupla(BaseModel):
    contacto: Contacto
    publica: bool = False


class Invitacion(BaseModel):
    etiqueta: str = Field(default="", max_length=50)


class AltaPersonal(BaseModel):
    correo: str = Field(max_length=254)
    rol: Literal["dupla", "curador", "admin"]
    dupla: UUID | None = None


class EstadoUsuario(BaseModel):
    activo: bool


class Canal(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    telefono: str = Field(pattern=r"^\+?[0-9 -]{3,22}$")
    uso: str = Field(min_length=3, max_length=260)
    region: str | None = Field(default=None, max_length=80)
    orden: int = Field(default=50, ge=0, le=1000)
    aprobado: bool = False


class Ubicacion(BaseModel):
    region: str = Field(min_length=2, max_length=80)
    comuna: str = Field(min_length=2, max_length=80)
    latitud: float = Field(ge=-57, le=-17)
    longitud: float = Field(ge=-110, le=-66)
    direccion: str = Field(min_length=3, max_length=180)
    horario: str = Field(min_length=3, max_length=180)


class Recurso(BaseModel):
    serie: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    clase: Literal["documento", "infografia", "testimonio", "guia", "establecimiento"]
    categoria: str = Field(pattern=r"^CAT-0[1-5]$")
    titulo: str = Field(min_length=3, max_length=220)
    descripcion: str = Field(min_length=20, max_length=150_000)
    enlace: str | None = Field(default=None, max_length=500)
    licencia: str = Field(min_length=3, max_length=150)
    vigencia: Literal["vigente", "diferida", "derogada", "no_aplica"]
    autor: str = Field(default="", max_length=180)
    anio: int | None = Field(default=None, ge=1900, le=2100)
    prioridad: int = Field(default=5, ge=1, le=5)
    ubicacion: Ubicacion | None = None


class Publicacion(BaseModel):
    autoriza_uso: Literal[True]
    sin_datos_identificatorios: Literal[True]


class ArchivoFuente(BaseModel):
    nombre: str = Field(min_length=4, max_length=160)
    datos: str = Field(min_length=4, max_length=2_800_000)


def extraer_compartido(datos: ArchivoFuente) -> str:
    """Extraer texto para revisión. La carga nunca publica el resultado."""
    try:
        contenido = b64decode(datos.datos, validate=True)
    except CodigoInvalido:
        raise HTTPException(422, "Archivo inválido.") from None
    if len(contenido) > 2 * 1024 * 1024:
        raise HTTPException(413, "El archivo supera los 2 MB.")
    tipo = datos.nombre.lower().rsplit(".", 1)[-1]
    try:
        if tipo == "pdf" and contenido.startswith(b"%PDF"):
            from pypdf import PdfReader

            pdf = PdfReader(BytesIO(contenido))
            if pdf.is_encrypted or len(pdf.pages) > 40:
                raise ValueError
            texto = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
        elif tipo == "docx":
            with ZipFile(BytesIO(contenido)) as docx:
                info = docx.getinfo("word/document.xml")
                if info.file_size > 2 * 1024 * 1024:
                    raise ValueError
                datos_xml = docx.read(info)
            if b"<!DOCTYPE" in datos_xml or b"<!ENTITY" in datos_xml:
                raise ValueError
            raiz = ElementTree.fromstring(datos_xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            texto = "\n".join(
                "".join(t.text or "" for t in p.findall(".//w:t", ns))
                for p in raiz.findall(".//w:p", ns)
            )
        elif tipo == "txt":
            texto = contenido.decode("utf-8-sig")
        else:
            raise ValueError
    except (ValueError, KeyError, BadZipFile, ElementTree.ParseError):
        raise HTTPException(
            422, "Usa PDF con texto de hasta 40 páginas, DOCX o TXT UTF-8."
        ) from None
    if not texto.strip():
        raise HTTPException(
            422, "No se encontró texto. Revisa si el documento está escaneado."
        )
    if len(texto) > 150_000:
        raise HTTPException(422, "Divide el texto en archivos menores.")
    return texto


class Ajustes(BaseModel):
    retencion_dias: int = Field(ge=1, le=90)
    invitacion_dias: int = Field(ge=1, le=60)
    limite_fragmentos: int = Field(ge=1, le=10)
    umbral_local: float = Field(ge=0.0, le=1.0)


def enlace_invitacion(
    cur, actor: str, rol: str, dupla, etiqueta="", correo=None
) -> dict:
    dias = ajuste(cur, "invitacion_dias", 30) if rol == "familia" else 7
    uid = str(uuid4())
    token = secrets.token_urlsafe(32)
    vence = utc() + timedelta(days=dias)
    cur.execute(
        """INSERT INTO fae_portal.invitaciones(id,huella,dupla,rol,etiqueta,correo,caduca)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (uid, huella(token), dupla, rol, etiqueta, correo, vence),
    )
    auditar(cur, actor, "crear_invitacion", uid)
    return {"id": uid, "enlace": f"/portal#invitacion={token}", "caduca": vence}


def canales_portal(region: str | None = None) -> list[dict]:
    with transaccion() as cur:
        cur.execute(
            """SELECT nombre,telefono,uso,region FROM fae_portal.canales
               WHERE aprobado AND (region IS NULL OR region=%s)
               ORDER BY region NULLS FIRST,orden,nombre""",
            (region,),
        )
        return list(cur.fetchall())


def router_gestion(demo: bool = True) -> APIRouter:
    router = APIRouter(prefix="/api/portal")

    @router.get("/programas")
    def programas(region: str | None = None):
        if region and len(region) > 80:
            raise HTTPException(422, "Región inválida.")
        with transaccion() as cur:
            cur.execute(
                """SELECT programa,region,
                      contacto - 'emergencia' - 'psicologia' - 'trabajo_social' AS contacto
                   FROM fae_portal.duplas WHERE activa AND publica
                     AND (%s::text IS NULL OR lower(region)=lower(%s))
                   ORDER BY region,programa LIMIT 250""",
                (region, region),
            )
            return list(cur.fetchall())

    @router.get("/contenido-publico")
    def contenido_publico():
        with transaccion() as cur:
            cur.execute(
                """SELECT id::text,clase,categoria,titulo,left(descripcion,800) AS descripcion,
                          enlace,licencia,autor,anio,ubicacion
                   FROM fae_portal.recursos WHERE estado='publicado'
                     AND vigencia NOT IN ('derogada','diferida') AND clase!='documento'
                   ORDER BY prioridad,creado_en DESC LIMIT 250"""
            )
            return list(cur.fetchall())

    @router.get("/duplas")
    def listar_duplas(request: Request):
        titular(request, "curador", "admin")
        with transaccion() as cur:
            cur.execute(
                "SELECT id::text,programa,region,contacto,publica,activa FROM fae_portal.duplas ORDER BY programa LIMIT 250"
            )
            return list(cur.fetchall())

    @router.post("/duplas", status_code=201)
    def crear_dupla(datos: Dupla, request: Request):
        persona = titular(request, "curador", "admin")
        uid = str(uuid4())
        with transaccion() as cur:
            cur.execute(
                """INSERT INTO fae_portal.duplas(id,programa,region,contacto,publica,activa)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    uid,
                    datos.programa,
                    datos.region,
                    Json(datos.contacto.model_dump()),
                    datos.publica,
                    datos.activa,
                ),
            )
            auditar(cur, persona["id"], "crear_dupla", uid)
        return {"id": uid}

    @router.put("/duplas/{uid}")
    def cambiar_dupla(uid: UUID, datos: Dupla, request: Request):
        persona = titular(request, "curador", "admin")
        uid = str(uid)
        with transaccion() as cur:
            cur.execute(
                """UPDATE fae_portal.duplas SET programa=%s,region=%s,contacto=%s,
                   publica=%s,activa=%s WHERE id=%s""",
                (
                    datos.programa,
                    datos.region,
                    Json(datos.contacto.model_dump()),
                    datos.publica,
                    datos.activa,
                    uid,
                ),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Dupla no encontrada.")
            if not datos.activa:
                cur.execute(
                    """DELETE FROM fae_portal.sesiones s USING fae_portal.usuarios u
                       WHERE u.dupla=%s AND u.rol='dupla' AND s.usuario=u.id""",
                    (uid,),
                )
                cur.execute(
                    "UPDATE fae_portal.invitaciones SET revocada=true WHERE dupla=%s AND usada_en IS NULL",
                    (uid,),
                )
            auditar(cur, persona["id"], "actualizar_dupla", uid)
        return {"id": uid}

    @router.get("/mi-dupla")
    def mi_dupla(request: Request):
        persona = titular(request, "dupla")
        with transaccion() as cur:
            cur.execute(
                "SELECT programa,region,contacto,publica FROM fae_portal.duplas WHERE id=%s AND activa",
                (persona["dupla"],),
            )
            fila = cur.fetchone()
        if not fila:
            raise HTTPException(403, "El programa asociado no está activo.")
        return fila

    @router.put("/mi-dupla")
    def cambiar_contacto(datos: ContactoDupla, request: Request):
        persona = titular(request, "dupla")
        with transaccion() as cur:
            cur.execute(
                "UPDATE fae_portal.duplas SET contacto=%s,publica=%s WHERE id=%s AND activa",
                (Json(datos.contacto.model_dump()), datos.publica, persona["dupla"]),
            )
            if not cur.rowcount:
                raise HTTPException(403, "El programa asociado no está activo.")
            auditar(cur, persona["id"], "actualizar_contacto", persona["dupla"])
        return {"estado": "actualizado"}

    @router.post("/personal/invitar", status_code=201)
    def invitar_personal(datos: AltaPersonal, request: Request):
        persona = titular(request, "curador", "admin")
        if persona["rol"] == "curador" and datos.rol != "dupla":
            raise HTTPException(403, "Solo puedes invitar integrantes de una dupla.")
        if (datos.rol == "dupla") != (datos.dupla is not None):
            raise HTTPException(422, "Asocia una dupla solo a sus integrantes.")
        correo = correo_normalizado(datos.correo)
        with transaccion() as cur:
            if datos.dupla:
                cur.execute(
                    "SELECT 1 FROM fae_portal.duplas WHERE id=%s AND activa",
                    (str(datos.dupla),),
                )
                if not cur.fetchone():
                    raise HTTPException(404, "Dupla activa no encontrada.")
            return enlace_invitacion(
                cur,
                persona["id"],
                datos.rol,
                str(datos.dupla) if datos.dupla else None,
                correo=correo,
            )

    @router.get("/personal")
    def listar_personal(request: Request):
        titular(request, "admin")
        with transaccion() as cur:
            cur.execute(
                """SELECT id::text,correo,rol,dupla::text,activo,verificado,totp IS NOT NULL AS mfa
                   FROM fae_portal.usuarios WHERE rol!='familia' ORDER BY correo LIMIT 250"""
            )
            return list(cur.fetchall())

    @router.put("/personal/{uid}")
    def cambiar_personal(uid: UUID, datos: EstadoUsuario, request: Request):
        persona = titular(request, "admin")
        uid = str(uid)
        if persona["id"] == uid:
            raise HTTPException(
                409, "Gestiona la baja desde otra cuenta administradora."
            )
        with transaccion() as cur:
            cur.execute(
                "UPDATE fae_portal.usuarios SET activo=%s WHERE id=%s AND rol!='familia'",
                (datos.activo, uid),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Cuenta del personal no encontrada.")
            if not datos.activo:
                cur.execute("DELETE FROM fae_portal.sesiones WHERE usuario=%s", (uid,))
            auditar(cur, persona["id"], "actualizar_personal", uid)
        return {"estado": "actualizado"}

    @router.post("/invitaciones", status_code=201)
    def invitar_familia(datos: Invitacion, request: Request):
        persona = titular(request, "dupla")
        with transaccion() as cur:
            cur.execute(
                "SELECT 1 FROM fae_portal.duplas WHERE id=%s AND activa",
                (persona["dupla"],),
            )
            if not cur.fetchone():
                raise HTTPException(403, "La dupla está inactiva.")
            return enlace_invitacion(
                cur, persona["id"], "familia", persona["dupla"], datos.etiqueta
            )

    @router.get("/invitaciones")
    def invitaciones(request: Request):
        persona = titular(request, "dupla")
        with transaccion() as cur:
            cur.execute(
                """SELECT i.id::text,i.etiqueta,i.caduca,
                         CASE WHEN i.revocada THEN 'revocada' WHEN i.usada_en IS NOT NULL THEN 'usada'
                              WHEN i.caduca<=now() THEN 'vencida' ELSE 'pendiente' END AS estado,
                         COALESCE(u.dupla=i.dupla,false) AS vinculada
                   FROM fae_portal.invitaciones i LEFT JOIN fae_portal.usuarios u ON i.usada_por=u.id
                   WHERE i.dupla=%s AND i.rol='familia'
                   ORDER BY i.caduca DESC LIMIT 250""",
                (persona["dupla"],),
            )
            return list(cur.fetchall())

    @router.post("/invitaciones/{uid}/revocar")
    def revocar(uid: UUID, request: Request):
        persona = titular(request, "dupla")
        uid = str(uid)
        with transaccion() as cur:
            cur.execute(
                """UPDATE fae_portal.invitaciones SET revocada=true WHERE id=%s
                   AND dupla=%s AND rol='familia' AND usada_en IS NULL""",
                (uid, persona["dupla"]),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Invitación sin usar no encontrada.")
            auditar(cur, persona["id"], "revocar_invitacion", uid)
        return {"estado": "revocada"}

    @router.post("/invitaciones/{uid}/desvincular")
    def desvincular(uid: UUID, request: Request):
        persona = titular(request, "dupla")
        uid = str(uid)
        with transaccion() as cur:
            cur.execute(
                """UPDATE fae_portal.usuarios u SET dupla=NULL FROM fae_portal.invitaciones i
                   WHERE i.id=%s AND i.dupla=%s AND i.usada_por=u.id AND u.dupla=i.dupla
                     AND i.rol='familia' AND u.rol='familia'""",
                (uid, persona["dupla"]),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Vínculo no encontrado.")
            auditar(cur, persona["id"], "desvincular", uid)
        return {"estado": "desvinculada"}

    @router.get("/canales")
    def gestionar_canales(request: Request):
        titular(request, "curador")
        with transaccion() as cur:
            cur.execute(
                "SELECT id::text,nombre,telefono,uso,region,orden,aprobado FROM fae_portal.canales ORDER BY orden LIMIT 250"
            )
            return list(cur.fetchall())

    @router.put("/canales/{uid}")
    def guardar_canal(uid: UUID, datos: Canal, request: Request):
        persona = titular(request, "curador")
        uid = str(uid)
        with transaccion() as cur:
            cur.execute(
                """INSERT INTO fae_portal.canales VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET nombre=EXCLUDED.nombre,telefono=EXCLUDED.telefono,
                   uso=EXCLUDED.uso,region=EXCLUDED.region,orden=EXCLUDED.orden,aprobado=EXCLUDED.aprobado""",
                (
                    uid,
                    datos.nombre,
                    datos.telefono,
                    datos.uso,
                    datos.region,
                    datos.orden,
                    datos.aprobado,
                ),
            )
            auditar(cur, persona["id"], "actualizar_canal", uid)
        return {"id": uid}

    @router.get("/recursos")
    def listar_recursos(request: Request):
        titular(request, "curador")
        with transaccion() as cur:
            cur.execute(
                """SELECT id::text,serie,clase,categoria,titulo,licencia,vigencia,estado
                   FROM fae_portal.recursos ORDER BY creado_en DESC LIMIT 250"""
            )
            return list(cur.fetchall())

    @router.post("/recursos/extraer")
    def extraer_archivo(datos: ArchivoFuente, request: Request):
        from pypdf.errors import PdfReadError

        from .portal_auth import limitar

        titular(request, "curador")
        limitar("extraer_recurso", request, 8)
        try:
            return {"texto": extraer_compartido(datos)}
        except PdfReadError:
            raise HTTPException(422, "No se pudo leer el PDF.") from None

    @router.post("/recursos", status_code=201)
    def preparar_recurso(datos: Recurso, request: Request):
        persona = titular(request, "curador")
        if (datos.clase == "establecimiento") != (datos.ubicacion is not None):
            raise HTTPException(422, "Indica ubicación solo para establecimientos.")
        if datos.enlace:
            uri = urlparse(datos.enlace)
            if uri.scheme != "https" or not uri.hostname or uri.username:
                raise HTTPException(422, "El enlace debe ser público y usar HTTPS.")
        uid = str(uuid4())
        with transaccion() as cur:
            cur.execute(
                """INSERT INTO fae_portal.recursos
                   (id,serie,clase,categoria,titulo,descripcion,enlace,licencia,vigencia,autor,anio,prioridad,estado,ubicacion)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'borrador',%s)""",
                (
                    uid,
                    datos.serie,
                    datos.clase,
                    datos.categoria,
                    datos.titulo,
                    datos.descripcion,
                    datos.enlace,
                    datos.licencia,
                    datos.vigencia,
                    datos.autor,
                    datos.anio,
                    datos.prioridad,
                    Json(datos.ubicacion.model_dump()) if datos.ubicacion else None,
                ),
            )
            auditar(cur, persona["id"], "preparar_recurso", uid)
        return {"id": uid}

    @router.post("/recursos/{uid}/publicar")
    def publicar(uid: UUID, _datos: Publicacion, request: Request):
        persona = titular(request, "curador")
        uid = str(uid)
        fragmentos = []
        if not demo:
            from .portal_indice import guardar_fragmentos, vectorizar_recurso

            with transaccion() as cur:
                cur.execute(
                    "SELECT clase,titulo,descripcion FROM fae_portal.recursos WHERE id=%s AND estado='borrador'",
                    (uid,),
                )
                borrador = cur.fetchone()
                if not borrador:
                    raise HTTPException(404, "Borrador no encontrado.")
            if borrador["clase"] in ("documento", "guia"):
                fragmentos = vectorizar_recurso(
                    borrador["titulo"], borrador["descripcion"]
                )
        with transaccion() as cur:
            cur.execute(
                "SELECT serie FROM fae_portal.recursos WHERE id=%s AND estado='borrador'",
                (uid,),
            )
            recurso = cur.fetchone()
            if not recurso:
                raise HTTPException(404, "Borrador no encontrado.")
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (recurso["serie"],)
            )
            cur.execute(
                "SELECT 1 FROM fae_portal.recursos WHERE id=%s AND estado='borrador' FOR UPDATE",
                (uid,),
            )
            if not cur.fetchone():
                raise HTTPException(409, "La versión ya se procesó.")
            if fragmentos:
                guardar_fragmentos(cur, uid, fragmentos)
            cur.execute(
                "UPDATE fae_portal.recursos SET estado='retirado' WHERE serie=%s AND estado='publicado' RETURNING id::text",
                (recurso["serie"],),
            )
            anterior = cur.fetchone()
            cur.execute(
                "UPDATE fae_portal.recursos SET estado='publicado' WHERE id=%s", (uid,)
            )
            if anterior:
                auditar(cur, persona["id"], "reemplazar_recurso", anterior["id"])
            auditar(cur, persona["id"], "publicar_recurso", uid)
        return {"estado": "publicado", "vectores_generados": len(fragmentos)}

    @router.post("/recursos/{uid}/retirar")
    def retirar(uid: UUID, request: Request):
        persona = titular(request, "curador")
        uid = str(uid)
        with transaccion() as cur:
            cur.execute(
                "UPDATE fae_portal.recursos SET estado='retirado' WHERE id=%s AND estado='publicado'",
                (uid,),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Recurso publicado no encontrado.")
            auditar(cur, persona["id"], "retirar_recurso", uid)
        return {"estado": "retirado"}

    @router.get("/ajustes")
    def leer_ajustes(request: Request):
        titular(request, "admin")
        base = Ajustes(
            retencion_dias=90,
            invitacion_dias=30,
            limite_fragmentos=3,
            umbral_local=0.84,
        )
        with transaccion() as cur:
            return {k: ajuste(cur, k, v) for k, v in base.model_dump().items()}

    @router.put("/ajustes")
    def guardar_ajustes(datos: Ajustes, request: Request):
        persona = titular(request, "admin")
        with transaccion() as cur:
            for k, v in datos.model_dump().items():
                anterior = ajuste(cur, k, None)
                cur.execute(
                    """INSERT INTO fae_portal.configuracion VALUES (%s,%s)
                       ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor""",
                    (k, Json(v)),
                )
                auditar(cur, persona["id"], "cambiar_ajuste", f"{k} {anterior} → {v}")
        return {"estado": "actualizado"}

    @router.get("/auditoria")
    def auditoria(request: Request):
        titular(request, "admin")
        with transaccion() as cur:
            cur.execute(
                "SELECT id,actor::text,accion,objeto,creado_en FROM fae_portal.auditoria ORDER BY id DESC LIMIT 250"
            )
            return list(cur.fetchall())

    @router.get("/metricas")
    def metricas(request: Request):
        titular(request, "curador", "admin")
        return leer_metricas()

    return router


def buscar_curado(pregunta: str, categoria: str | None, limite: int) -> list[dict]:
    """Consultar solamente versiones publicadas de textos de curaduría."""
    with transaccion() as cur:
        cur.execute(
            """WITH q AS (SELECT websearch_to_tsquery('spanish',%s) AS texto)
               SELECT r.id::text,r.titulo,r.categoria,r.descripcion,r.enlace,r.licencia,r.autor,r.anio,
                      r.prioridad,r.vigencia
               FROM fae_portal.recursos r, q
               WHERE r.estado='publicado' AND r.clase IN ('documento','guia')
                 AND r.vigencia IN ('vigente','no_aplica')
                 AND (%s::text IS NULL OR r.categoria=%s)
                 AND to_tsvector('spanish',r.titulo || ' ' || r.descripcion) @@ q.texto
               ORDER BY ts_rank_cd(to_tsvector('spanish',r.titulo || ' ' || r.descripcion),q.texto) DESC,
                        r.prioridad,r.id LIMIT %s""",
            (pregunta, categoria, categoria, limite),
        )
        filas = cur.fetchall()
    return [
        {
            "chunk_id": "web_" + f["id"].replace("-", ""),
            "categoria": f["categoria"],
            "seccion": f["categoria"],
            "fuente": f["titulo"],
            "contenido": f["descripcion"][:1800],
            "similitud": 0.0,
            "metadata": {
                **{k: v for k, v in f.items() if k != "descripcion"},
                "alcance_texto": "publicado_por_curaduria",
                "coincidencia_textual_curada": True,
            },
        }
        for f in filas
    ]
