"""Descarga y extracción de candidatos; no aprueba contenido automáticamente."""

import io
import json
import ssl
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .archivos import guardar_json
from .catalogo import leer_catalogo
from .configuracion import SALIDA_URLS


class TextoHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.oculto = 0
        self.textos = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.oculto += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.oculto = max(0, self.oculto - 1)

    def handle_data(self, data):
        if not self.oculto and data.strip():
            self.textos.append(data.strip())


def descargar(
    limite: int = 0,
    salida: Path = SALIDA_URLS,
    solo_ids: set[str] | None = None,
):
    """Descarga candidatos una vez por URL. No sigue enlaces de las fichas."""
    items = leer_catalogo(salida)
    folder = salida / "textos_candidatos"
    folder.mkdir(parents=True, exist_ok=True)
    (salida / "textos_aprobados").mkdir(exist_ok=True)
    registro_path = salida / "descargas.json"
    registros = (
        json.loads(registro_path.read_text(encoding="utf-8"))
        if registro_path.exists()
        else {}
    )
    intentos = 0
    for x in items:
        uid = x["url_id"]
        if solo_ids is not None and uid not in solo_ids:
            continue
        url = x.get("url_documento", x["url"])
        if x["tipo_enlace"] in (
            "busqueda_academica",
            "repositorio_general",
        ) and not x.get("url_documento"):
            registros[uid] = {"estado": "requiere_enlace_especifico", "url": x["url"]}
            continue
        if (
            (folder / f"{uid}.txt").exists()
            and registros.get(uid, {}).get("url_documento", x["url"]) == url
            and registros.get(uid, {}).get("extractor_pdf", "pypdf")
            == x.get("extractor_pdf", "pypdf")
        ):
            continue
        if limite and intentos >= limite:
            break
        intentos += 1
        try:
            req = Request(url, headers={"User-Agent": "FAE-Academic-Research/1.0"})
            try:
                response = urlopen(req, timeout=30)
            except URLError as exc:
                if not isinstance(exc.reason, ssl.SSLCertVerificationError):
                    raise
                import certifi

                response = urlopen(
                    req,
                    timeout=30,
                    context=ssl.create_default_context(cafile=certifi.where()),
                )
            with response as opened:
                raw = opened.read(25 * 1024 * 1024 + 1)
                if len(raw) > 25 * 1024 * 1024:
                    raise ValueError("Respuesta superior a 25 MB")
                final_url = opened.url
                content_type = opened.headers.get_content_type()
                charset = opened.headers.get_content_charset() or "utf-8"
            if raw.startswith(b"%PDF"):
                if x.get("extractor_pdf") == "pymupdf":
                    import pymupdf

                    documento = pymupdf.open(stream=raw, filetype="pdf")
                    try:
                        texto = "\n\n".join(p.get_text() for p in documento)
                    finally:
                        documento.close()
                else:
                    from pypdf import PdfReader

                    texto = "\n\n".join(
                        p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages
                    )
                formato = "pdf"
            elif content_type in ("text/html", "application/xhtml+xml"):
                parser = TextoHTML()
                parser.feed(raw.decode(charset, errors="replace"))
                texto, formato = "\n".join(parser.textos), "html"
            elif content_type == "text/plain":
                texto, formato = raw.decode(charset, errors="replace"), "txt"
            else:
                raise ValueError("Formato no soportado: " + content_type)
            if len(texto.strip()) < 300:
                registros[uid] = {
                    "estado": "incompleto",
                    "url": x["url"],
                    "url_documento": url,
                    "url_final": final_url,
                    "formato": formato,
                    "extractor_pdf": x.get("extractor_pdf", "pypdf"),
                    "caracteres": len(texto),
                    "motivo": "Menos de 300 caracteres; puede requerir OCR o acceso manual.",
                }
                guardar_json(registro_path, registros)
                print(uid, registros[uid]["estado"])
                continue
            (folder / f"{uid}.txt").write_text(texto, encoding="utf-8")
            registros[uid] = {
                "estado": "candidato_pendiente_revision",
                "url": x["url"],
                "url_documento": url,
                "url_final": final_url,
                "formato": formato,
                "extractor_pdf": x.get("extractor_pdf", "pypdf"),
                "caracteres": len(texto),
                "fecha_utc": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            registros[uid] = {
                "estado": "error",
                "url": x["url"],
                "url_documento": url,
                "error": str(e),
            }
        guardar_json(registro_path, registros)
        print(uid, registros[uid]["estado"])
        time.sleep(1)
    guardar_json(registro_path, registros)
