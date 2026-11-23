"""Operaciones del titular sobre acceso, perfil e historial."""

import json
import secrets
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

import pyotp
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg2.extras import Json
from pydantic import BaseModel, Field

from .orientacion import contiene_identificadores
from .portal_auth import (
    CONSENTIMIENTO,
    CONSENTIMIENTO_VERSION,
    HASHEADOR,
    SESION,
    cifrador,
    correo_normalizado,
    crear_sesion,
    enviar_token,
    huella,
    limitar,
    marcar_totp,
    titular,
    token_temporal,
    verificar_clave,
)
from .portal_db import ajuste, auditar, transaccion

CLAVE_FICTICIA = HASHEADOR.hash(secrets.token_urlsafe(24))


class Acceso(BaseModel):
    correo: str = Field(max_length=254)
    clave: str = Field(min_length=1, max_length=128)
    codigo: str | None = Field(default=None, pattern=r"^\d{6}$")


class Activacion(Acceso):
    invitacion: str = Field(min_length=30, max_length=128)
    consentimiento: Literal[True]
    version: Literal["demo-2026-11-v1"]


class Token(BaseModel):
    token: str = Field(min_length=30, max_length=128)


class NuevoFactor(Token):
    codigo: str = Field(pattern=r"^\d{6}$")


class SolicitudCorreo(BaseModel):
    correo: str = Field(max_length=254)


class CambioClave(Token):
    clave: str = Field(min_length=12, max_length=128)


class Confirmacion(BaseModel):
    clave: str = Field(min_length=1, max_length=128)
    confirmar: Literal[True]


class Perfil(BaseModel):
    inicio: date | None = None
    tramo: Literal["0-2", "3-5", "6-11", "12-17"] | None = None
    tipo: Literal["externa", "extensa", "urgencia"] | None = None
    egreso: bool = False


def historia(cur, uid: str) -> list[dict]:
    dias = ajuste(cur, "retencion_dias", 90)
    cur.execute(
        """SELECT id::text, creado_en, datos FROM fae_portal.turnos
           WHERE usuario=%s AND creado_en>now()-(%s * interval '1 day')
           ORDER BY creado_en DESC LIMIT 250""",
        (uid, dias),
    )
    filas = cur.fetchall()
    if not filas:
        return []
    llave = cifrador()
    return [
        {
            "id": f["id"],
            "fecha": f["creado_en"],
            **json.loads(llave.decrypt(bytes(f["datos"]))),
        }
        for f in filas
    ]


def guardar_turno(request: Request, pregunta: str, resultado: dict) -> None:
    if resultado["agente"]["modo"] in ("privacidad", "derivacion"):
        return
    persona = titular(request, opcional=True)
    if not persona or persona["rol"] != "familia":
        return
    resumen = resultado["respuesta"]
    if contiene_identificadores(pregunta + "\n" + resumen):
        return
    datos = cifrador().encrypt(
        json.dumps(
            {
                "pregunta": pregunta,
                "respuesta": resumen,
                "fuentes": resultado["fuentes"],
            },
            ensure_ascii=False,
        ).encode()
    )
    with transaccion() as cur:
        cur.execute(
            """INSERT INTO fae_portal.turnos(id,usuario,datos)
               SELECT %s,id,%s FROM fae_portal.usuarios WHERE id=%s AND activo""",
            (str(uuid4()), datos, persona["id"]),
        )
        cur.execute(
            """DELETE FROM fae_portal.turnos WHERE usuario=%s AND id IN
               (SELECT id FROM fae_portal.turnos WHERE usuario=%s
                ORDER BY creado_en DESC, id DESC OFFSET 250)""",
            (persona["id"], persona["id"]),
        )


def etapa(perfil: dict) -> dict:
    if perfil.get("egreso"):
        return {
            "estado": "Post egreso",
            "preguntas": [
                "¿Cómo cuidar a mi familia durante el duelo por el egreso?",
                "¿Qué información existe sobre el contacto después del egreso?",
            ],
        }
    inicio = perfil.get("inicio")
    if not inicio:
        return {
            "estado": "Sin fecha de inicio",
            "preguntas": [
                "¿Cómo preparar la llegada al acogimiento?",
                "¿Qué significa que el acogimiento sea transitorio?",
            ],
        }
    inicio = date.fromisoformat(inicio)
    hoy = date.today()
    meses = (hoy.year - inicio.year) * 12 + hoy.month - inicio.month
    preguntas = [
        "¿Cómo preparar gradualmente el egreso?",
        "¿Cómo acompañar los cambios durante el acogimiento?",
    ]
    if meses < 12:
        preguntas.insert(0, "¿Qué apoyos necesita una familia que empieza a acoger?")
    return {"meses": meses, "estado": "Acogimiento", "preguntas": preguntas}


def obtener_invitacion(cur, valor: str):
    cur.execute(
        """SELECT i.* FROM fae_portal.invitaciones i LEFT JOIN fae_portal.duplas d ON d.id=i.dupla
           WHERE i.huella=%s AND i.caduca>now() AND NOT i.revocada AND i.usada_en IS NULL
             AND (i.dupla IS NULL OR d.activa) FOR UPDATE OF i""",
        (huella(valor),),
    )
    existe = cur.fetchone()
    if not existe:
        raise HTTPException(
            410, "El enlace venció, se revocó o ya fue usado. Solicita uno nuevo."
        )
    return existe


def usar_invitacion(cur, inv, uid: str) -> None:
    cur.execute(
        "UPDATE fae_portal.invitaciones SET usada_en=now(), usada_por=%s WHERE id=%s",
        (uid, inv["id"]),
    )


def router_cuentas(demo: bool) -> APIRouter:
    router = APIRouter(prefix="/api/portal")

    @router.get("/consentimiento")
    def consentimiento():
        with transaccion() as cur:
            retencion = ajuste(cur, "retencion_dias", 90)
        return {
            "version": CONSENTIMIENTO_VERSION,
            "texto": CONSENTIMIENTO,
            "retencion_dias": retencion,
            "demo": demo,
        }

    @router.post("/activar")
    def activar(datos: Activacion, request: Request):
        correo = correo_normalizado(datos.correo)
        if demo and not correo.endswith(".test"):
            raise HTTPException(
                422, "Usa un correo ficticio terminado en .test para la demo."
            )
        limitar("activar", request, 8, correo)
        if len(datos.clave) < 12:
            raise HTTPException(422, "Usa al menos 12 caracteres en la contraseña.")
        clave = HASHEADOR.hash(datos.clave)
        uid = str(uuid4())
        with transaccion() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (correo,))
            inv = obtener_invitacion(cur, datos.invitacion)
            if inv["correo"] and inv["correo"] != correo:
                raise HTTPException(403, "La invitación corresponde a otro correo.")
            cur.execute("SELECT 1 FROM fae_portal.usuarios WHERE correo=%s", (correo,))
            if cur.fetchone():
                raise HTTPException(
                    409,
                    "Si ya tienes cuenta, entra y acepta la invitación desde tu perfil.",
                )
            cur.execute(
                """INSERT INTO fae_portal.usuarios(id,correo,clave,rol,dupla,consentimiento,consentido_en)
                   VALUES (%s,%s,%s,%s,%s,%s,now())""",
                (uid, correo, clave, inv["rol"], inv["dupla"], datos.version),
            )
            usar_invitacion(cur, inv, uid)
            token = token_temporal(cur, uid, "verificar", 60)
        return enviar_token(correo, "verificar", token, demo)

    @router.post("/verificacion/reenviar")
    def reenviar(datos: SolicitudCorreo, request: Request):
        correo = correo_normalizado(datos.correo)
        limitar("reenviar", request, 5, correo)
        with transaccion() as cur:
            cur.execute(
                "SELECT id::text FROM fae_portal.usuarios WHERE correo=%s AND activo AND NOT verificado FOR UPDATE",
                (correo,),
            )
            u = cur.fetchone()
            token = token_temporal(cur, u["id"], "verificar", 60) if u else None
        return (
            enviar_token(correo, "verificar", token, demo)
            if token
            else {"estado": "correo_solicitado"}
        )

    @router.post("/verificar")
    def verificar(datos: Token, request: Request):
        limitar("verificar", request, 15)
        with transaccion() as cur:
            cur.execute(
                """DELETE FROM fae_portal.tokens WHERE huella=%s AND tipo='verificar'
                   AND caduca>now() RETURNING usuario""",
                (huella(datos.token),),
            )
            fila = cur.fetchone()
            if not fila:
                raise HTTPException(410, "El enlace de verificación ya no es válido.")
            cur.execute(
                "UPDATE fae_portal.usuarios SET verificado=true WHERE id=%s",
                (fila["usuario"],),
            )
        return {"estado": "verificado"}

    @router.post("/entrar")
    def entrar(datos: Acceso, request: Request, response: Response):
        correo = correo_normalizado(datos.correo)
        limitar("entrar", request, 18, correo)
        with transaccion() as cur:
            cur.execute(
                """SELECT id::text,clave,rol,totp,ultimo_totp,activo,verificado,
                          rol!='dupla' OR EXISTS (SELECT 1 FROM fae_portal.duplas d
                              WHERE d.id=u.dupla AND d.activa) AS equipo_activo
                   FROM fae_portal.usuarios u WHERE correo=%s FOR UPDATE""",
                (correo,),
            )
            u = cur.fetchone()
            valido = verificar_clave(u["clave"] if u else CLAVE_FICTICIA, datos.clave)
            if not (
                u and valido and u["activo"] and u["verificado"] and u["equipo_activo"]
            ):
                raise HTTPException(
                    401, "Credenciales incorrectas o cuenta sin activar."
                )
            if u["rol"] != "familia":
                if u["totp"] is None:
                    semilla = pyotp.random_base32()
                    token = token_temporal(
                        cur,
                        u["id"],
                        "alta_mfa",
                        10,
                        cifrador().encrypt(semilla.encode()),
                    )
                    uri = pyotp.TOTP(semilla).provisioning_uri(
                        name=correo, issuer_name="Asistente FAE"
                    )
                    return {
                        "estado": "configurar_mfa",
                        "token": token,
                        "semilla": semilla,
                        "uri": uri,
                    }
                if not datos.codigo:
                    return {"estado": "requiere_mfa"}
                marcar_totp(cur, u["id"], u["totp"], datos.codigo, u["ultimo_totp"])
            crear_sesion(cur, u["id"], response, request)
        return {"estado": "activo", "rol": u["rol"]}

    @router.post("/mfa/confirmar")
    def confirmar_factor(datos: NuevoFactor, request: Request, response: Response):
        limitar("mfa", request, 12)
        with transaccion() as cur:
            cur.execute(
                """SELECT u.id::text,u.rol,u.totp,u.ultimo_totp,t.secreto
                   FROM fae_portal.tokens t JOIN fae_portal.usuarios u ON u.id=t.usuario
                   WHERE t.huella=%s AND t.tipo='alta_mfa' AND t.caduca>now()
                     AND u.activo AND u.verificado FOR UPDATE OF t,u""",
                (huella(datos.token),),
            )
            u = cur.fetchone()
            if not u or u["totp"] or u["rol"] == "familia":
                raise HTTPException(410, "La configuración del segundo factor caducó.")
            marcar_totp(cur, u["id"], u["secreto"], datos.codigo, u["ultimo_totp"])
            cur.execute(
                "UPDATE fae_portal.usuarios SET totp=%s WHERE id=%s",
                (u["secreto"], u["id"]),
            )
            cur.execute(
                "DELETE FROM fae_portal.tokens WHERE huella=%s", (huella(datos.token),)
            )
            auditar(cur, u["id"], "activar_mfa", u["id"])
            crear_sesion(cur, u["id"], response, request)
        return {"estado": "activo", "rol": u["rol"]}

    @router.post("/salir")
    def salir(request: Request, response: Response):
        token = request.cookies.get(SESION, "")
        if token and len(token) < 128:
            with transaccion() as cur:
                cur.execute(
                    "DELETE FROM fae_portal.sesiones WHERE huella=%s", (huella(token),)
                )
        response.delete_cookie(SESION, path="/")
        return {"estado": "cerrada"}

    @router.post("/restablecer/solicitar")
    def solicitar_restablecimiento(datos: SolicitudCorreo, request: Request):
        correo = correo_normalizado(datos.correo)
        limitar("restablecer", request, 5, correo)
        with transaccion() as cur:
            cur.execute(
                """SELECT id::text FROM fae_portal.usuarios
                   WHERE correo=%s AND activo AND verificado FOR UPDATE""",
                (correo,),
            )
            u = cur.fetchone()
            token = token_temporal(cur, u["id"], "restablecer", 60) if u else None
        if token:
            return enviar_token(correo, "restablecer", token, demo)
        return {"estado": "correo_solicitado"}

    @router.post("/restablecer")
    def restablecer(datos: CambioClave, request: Request):
        limitar("cambiar_clave", request, 10)
        clave = HASHEADOR.hash(datos.clave)
        with transaccion() as cur:
            cur.execute(
                """DELETE FROM fae_portal.tokens WHERE huella=%s AND tipo='restablecer'
                   AND caduca>now() RETURNING usuario""",
                (huella(datos.token),),
            )
            fila = cur.fetchone()
            if not fila:
                raise HTTPException(410, "El enlace de recuperación ya no es válido.")
            cur.execute(
                "UPDATE fae_portal.usuarios SET clave=%s WHERE id=%s",
                (clave, fila["usuario"]),
            )
            cur.execute(
                "DELETE FROM fae_portal.sesiones WHERE usuario=%s", (fila["usuario"],)
            )
            cur.execute(
                "DELETE FROM fae_portal.tokens WHERE usuario=%s AND tipo='alta_mfa'",
                (fila["usuario"],),
            )
        return {"estado": "clave_actualizada"}

    @router.get("/yo")
    def yo(request: Request):
        persona = titular(request)
        if persona["rol"] == "familia":
            with transaccion() as cur:
                cur.execute(
                    "SELECT programa,region,contacto FROM fae_portal.duplas WHERE id=%s AND activa",
                    (persona["dupla"],),
                )
                persona["contacto_dupla"] = cur.fetchone()
            persona["etapa"] = etapa(persona["perfil"])
        return persona

    @router.put("/perfil")
    def editar_perfil(datos: Perfil, request: Request):
        persona = titular(request, "familia")
        if datos.inicio and datos.inicio.replace(day=1) > date.today():
            raise HTTPException(422, "Indica un mes de inicio que ya haya comenzado.")
        perfil = datos.model_dump(mode="json")
        if datos.inicio:
            perfil["inicio"] = datos.inicio.replace(day=1).isoformat()
        with transaccion() as cur:
            cur.execute(
                "UPDATE fae_portal.usuarios SET perfil=%s WHERE id=%s",
                (Json(perfil), persona["id"]),
            )
        return {"perfil": perfil, "etapa": etapa(perfil)}

    @router.post("/reasociar")
    def reasociar(datos: Token, request: Request):
        persona = titular(request, "familia")
        with transaccion() as cur:
            inv = obtener_invitacion(cur, datos.token)
            if inv["rol"] != "familia" or (
                inv["correo"] and inv["correo"] != persona["correo"]
            ):
                raise HTTPException(403, "La invitación corresponde a otra cuenta.")
            cur.execute(
                "UPDATE fae_portal.usuarios SET dupla=%s WHERE id=%s",
                (inv["dupla"], persona["id"]),
            )
            usar_invitacion(cur, inv, persona["id"])
        return {"estado": "vinculada"}

    @router.get("/historial")
    def historial(request: Request):
        persona = titular(request, "familia")
        with transaccion() as cur:
            return historia(cur, persona["id"])

    @router.delete("/historial/{uid}")
    def borrar_turno(uid: UUID, request: Request):
        persona = titular(request, "familia")
        with transaccion() as cur:
            cur.execute(
                "DELETE FROM fae_portal.turnos WHERE id=%s AND usuario=%s",
                (str(uid), persona["id"]),
            )
            if not cur.rowcount:
                raise HTTPException(404, "Entrada no encontrada.")
        return {"estado": "borrada"}

    @router.get("/mis-datos")
    def descargar(request: Request):
        persona = titular(request, "familia")
        with transaccion() as cur:
            cur.execute(
                "SELECT consentido_en FROM fae_portal.usuarios WHERE id=%s",
                (persona["id"],),
            )
            persona["consentido_en"] = cur.fetchone()["consentido_en"]
            persona["historial"] = historia(cur, persona["id"])
        return Response(
            json.dumps(persona, default=str, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="datos-fae.json"',
                "Cache-Control": "no-store",
            },
        )

    @router.post("/borrar-cuenta")
    def borrar_cuenta(datos: Confirmacion, request: Request, response: Response):
        persona = titular(request, "familia")
        limitar("borrar", request, 6, persona["correo"])
        with transaccion() as cur:
            cur.execute(
                "SELECT clave FROM fae_portal.usuarios WHERE id=%s FOR UPDATE",
                (persona["id"],),
            )
            u = cur.fetchone()
            if not u or not verificar_clave(u["clave"], datos.clave):
                raise HTTPException(403, "Contraseña incorrecta.")
            cur.execute("DELETE FROM fae_portal.usuarios WHERE id=%s", (persona["id"],))
        response.delete_cookie(SESION, path="/")
        return {"estado": "borrada"}

    return router
