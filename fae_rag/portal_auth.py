"""Credenciales, sesiones opacas, invitaciones y segundo factor TOTP."""

import hashlib
import json
import os
import re
import secrets
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from smtplib import SMTP_SSL
from ssl import create_default_context
from urllib.request import Request as PeticionCorreo
from urllib.request import urlopen
from uuid import uuid4

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Response

from .portal_db import auditar, transaccion

SESION = "fae_sesion"
HASHEADOR = PasswordHasher(time_cost=3, memory_cost=19456, parallelism=1)
CONSENTIMIENTO_VERSION = "demo-2026-11-v1"
CONSENTIMIENTO = (
    "Guardamos tu correo, el consentimiento y el perfil opcional para darte acceso "
    "al portal. El historial solo se guarda cuando eliges guardarlo y vence según "
    "el plazo indicado en tu cuenta. Solo tú puedes consultarlo, descargarlo o "
    "borrarlo. Tu dupla puede gestionar el vínculo desde su invitación. "
    "En la demostración usa datos inventados."
)


def utc() -> datetime:
    return datetime.now(timezone.utc)


def huella(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def cifrador() -> Fernet:
    secreto = os.getenv("FAE_PORTAL_SECRETO", "")
    if len(secreto) < 32:
        raise RuntimeError(
            "FAE_PORTAL_SECRETO requiere al menos 32 caracteres aleatorios."
        )
    return Fernet(urlsafe_b64encode(hashlib.sha256(secreto.encode()).digest()))


def correo_normalizado(correo: str) -> str:
    correo = correo.strip().casefold()
    if len(correo) > 254 or not re.fullmatch(
        r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", correo
    ):
        raise HTTPException(422, "Ingresa un correo válido.")
    return correo


def limitar(accion: str, request: Request, maximo: int, destino: str = "") -> None:
    """Contadores temporales separados por origen y, si se conoce, por cuenta."""
    ip = request.client.host if request.client else "anonimo"
    secreto = os.environ["FAE_PORTAL_SECRETO"]
    claves = [huella(f"{secreto}|{accion}|ip|{ip}")]
    if destino:
        claves.append(huella(f"{secreto}|{accion}|cuenta|{destino}"))
    with transaccion() as cur:
        cur.execute("DELETE FROM fae_portal.limites WHERE vence < now()")
        autorizado = True
        for clave in claves:
            cur.execute(
                """INSERT INTO fae_portal.limites VALUES (%s, now()+interval '10 minutes', 1)
                   ON CONFLICT (huella) DO UPDATE SET cantidad=fae_portal.limites.cantidad+1
                   RETURNING cantidad""",
                (clave,),
            )
            permitido = cur.fetchone()["cantidad"] <= maximo
            autorizado = autorizado and permitido
    if not autorizado:
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")


def verificar_clave(clave_hash: str, clave: str) -> bool:
    try:
        return HASHEADOR.verify(clave_hash, clave)
    except VerificationError:
        return False


def crear_sesion(cur, uid: str, response: Response, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    cur.execute("DELETE FROM fae_portal.sesiones WHERE caduca <= now()")
    cur.execute(
        "INSERT INTO fae_portal.sesiones(huella,usuario,caduca) VALUES (%s,%s,%s)",
        (huella(token), uid, utc() + timedelta(hours=8)),
    )
    response.set_cookie(
        SESION,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https" or os.getenv("RENDER") == "true",
        max_age=8 * 3600,
        path="/",
    )


def titular(request: Request, *roles: str, opcional: bool = False) -> dict | None:
    token = request.cookies.get(SESION, "")
    if token and len(token) < 128:
        with transaccion() as cur:
            cur.execute(
                """UPDATE fae_portal.sesiones s SET vista=now() FROM fae_portal.usuarios u
                   WHERE s.huella=%s AND s.usuario=u.id AND s.caduca>now()
                     AND s.vista>now()-interval '30 minutes' AND u.activo AND u.verificado
                     AND (u.rol!='dupla' OR EXISTS (
                         SELECT 1 FROM fae_portal.duplas d WHERE d.id=u.dupla AND d.activa
                     ))
                   RETURNING u.id::text, u.correo, u.rol, u.dupla::text, u.perfil, u.consentimiento""",
                (huella(token),),
            )
            persona = cur.fetchone()
        if persona:
            if roles and persona["rol"] not in roles:
                raise HTTPException(403, "Tu cuenta no tiene este permiso.")
            return dict(persona)
    if opcional:
        return None
    raise HTTPException(401, "Inicia sesión para continuar.")


def token_temporal(
    cur, uid: str, tipo: str, minutos: int, secreto: bytes | None = None
) -> str:
    cur.execute(
        "DELETE FROM fae_portal.tokens WHERE caduca <= now() OR (usuario=%s AND tipo=%s)",
        (uid, tipo),
    )
    valor = secrets.token_urlsafe(32)
    cur.execute(
        "INSERT INTO fae_portal.tokens VALUES (%s,%s,%s,%s,%s)",
        (huella(valor), uid, tipo, secreto, utc() + timedelta(minutes=minutos)),
    )
    return valor


def marcar_totp(cur, uid: str, secreto: bytes, codigo: str, ultimo: int) -> None:
    semilla = cifrador().decrypt(bytes(secreto)).decode()
    totp = pyotp.TOTP(semilla)
    paso = int(time.time()) // totp.interval
    elegido = next(
        (
            n
            for n in (paso, paso - 1, paso + 1)
            if n > ultimo and secrets.compare_digest(totp.at(n * totp.interval), codigo)
        ),
        None,
    )
    if elegido is None:
        raise HTTPException(401, "Código de autenticación inválido o ya usado.")
    cur.execute(
        "UPDATE fae_portal.usuarios SET ultimo_totp=%s WHERE id=%s", (elegido, uid)
    )


def enviar_token(destino: str, tipo: str, token: str, demo: bool) -> dict:
    if demo:
        if not destino.endswith(".test"):
            raise HTTPException(
                422, "Usa un correo ficticio terminado en .test para la demo."
            )
        return {"estado": "prueba", "token_prueba": token}
    from email.message import EmailMessage

    host = os.getenv("FAE_SMTP_SERVIDOR")
    usuario = os.getenv("FAE_SMTP_USUARIO")
    clave = os.getenv("FAE_SMTP_CLAVE")
    origen = os.getenv("FAE_URL_PUBLICA", "").rstrip("/")
    if not origen.startswith("https://"):
        raise HTTPException(
            503, "Configura la URL HTTPS del portal para usar correo real."
        )
    fragmento = "verificar" if tipo == "verificar" else "restablecer"
    texto = (
        f"Completa la operación de tu cuenta FAE en {origen}/portal#{fragmento}={token}"
    )
    api_key = os.getenv("FAE_RESEND_API_KEY")
    remitente = os.getenv("FAE_CORREO_REMITENTE")
    if api_key and remitente:
        peticion = PeticionCorreo(
            "https://api.resend.com/emails",
            json.dumps(
                {
                    "from": remitente,
                    "to": [destino],
                    "subject": "Cuenta del Asistente FAE",
                    "text": texto,
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Asistente FAE",
            },
        )
        try:
            with urlopen(peticion, timeout=8):
                return {"estado": "correo_solicitado"}
        except OSError:
            raise HTTPException(
                503, "No se pudo enviar el correo de la cuenta."
            ) from None
    if not all((host, usuario, clave)):
        raise HTTPException(
            503, "El envío de correo requiere configuración institucional."
        )
    mensaje = EmailMessage()
    mensaje["From"] = usuario
    mensaje["To"] = destino
    mensaje["Subject"] = "Cuenta del Asistente FAE"
    mensaje.set_content(texto)
    try:
        with SMTP_SSL(
            host,
            int(os.getenv("FAE_SMTP_PUERTO", "465")),
            timeout=8,
            context=create_default_context(),
        ) as servidor:
            servidor.login(usuario, clave)
            servidor.send_message(mensaje)
    except OSError:
        raise HTTPException(503, "No se pudo enviar el correo de la cuenta.") from None
    return {"estado": "correo_solicitado"}


def inicializar_admin() -> None:
    correo = os.getenv("FAE_ADMIN_CORREO")
    clave = os.getenv("FAE_ADMIN_CLAVE")
    if not correo and not clave:
        return
    if not correo or not clave or len(clave) < 12:
        raise RuntimeError(
            "Configura correo y una clave inicial de al menos 12 caracteres."
        )
    correo = correo_normalizado(correo)
    with transaccion() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(749312802)")
        cur.execute("SELECT 1 FROM fae_portal.usuarios WHERE rol='admin' LIMIT 1")
        if not cur.fetchone():
            uid = str(uuid4())
            cur.execute(
                """INSERT INTO fae_portal.usuarios(id,correo,clave,rol,verificado)
                   VALUES (%s,%s,%s,'admin',true)""",
                (uid, correo, HASHEADOR.hash(clave)),
            )
            auditar(cur, uid, "admin_inicial", uid)
