"""Comprobar contrato HTTP de una instancia de demostración FAE."""

import argparse
import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CASOS = (
    ("¿Qué pasa durante el egreso y la transición?", "verde", "extractivo"),
    ("Estoy agotada y no doy más.", "amarillo", "abstencion"),
    ("El niño no respira.", "rojo", "derivacion"),
    ("¿Qué son los cuásares extragalácticos?", "verde", "abstencion"),
)

CASOS_DOCUMENTALES = (
    ("¿Cómo se prepara a una familia para el acogimiento?", "verde", "extractivo"),
    ("¿Cómo preparar pan de masa madre?", "verde", "abstencion"),
    ("El niño no respira.", "rojo", "derivacion"),
)


def solicitar(base: str, ruta: str, pregunta: str | None = None) -> tuple[str, str]:
    datos = json.dumps({"pregunta": pregunta}).encode() if pregunta else None
    req = Request(base + ruta, data=datos, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as respuesta:
        return respuesta.headers["Content-Type"], respuesta.read().decode("utf-8")


def comprobar(base: str, exigir_corpus: bool = False) -> None:
    _, salud = solicitar(base, "/api/salud")
    estado = json.loads(salud)
    if estado.get("modo") != "demo":
        raise RuntimeError("El sitio no se identificó como demostración.")
    corpus = estado.get("corpus", {})
    documental = corpus.get("tipo") == "documental" and corpus.get("vectores", 0) > 0
    if exigir_corpus and not documental:
        raise RuntimeError("El sitio aún no sirve el corpus documental.")
    casos = CASOS_DOCUMENTALES if documental else CASOS
    _, html = solicitar(base, "/")
    _, ayuda = solicitar(base, "/api/ayuda")
    if "Ayuda inmediata" not in html or not json.loads(ayuda)["demo"]:
        raise RuntimeError("El sitio no ofrece los controles previstos de la demo.")
    if estado.get("portal"):
        _, pantalla = solicitar(base, "/portal")
        _, consentimiento = solicitar(base, "/api/portal/consentimiento")
        if "Portal FAE" not in pantalla or not json.loads(consentimiento).get("demo"):
            raise RuntimeError("La ruta pública del portal no está disponible.")
    for pregunta, nivel, modo in casos:
        _, cuerpo = solicitar(base, "/api/consultar", pregunta)
        resultado = json.loads(cuerpo)
        if (resultado["orientacion"]["nivel"], resultado["agente"]["modo"]) != (
            nivel,
            modo,
        ):
            raise RuntimeError(f"Resultado no esperado para el caso sintético {nivel}.")
        if (modo == "extractivo") != bool(resultado["fuentes"]):
            raise RuntimeError(
                f"Las fuentes no coinciden con el caso sintético {nivel}."
            )
        if documental and any(
            fuente["chunk_id"].startswith("ref_demo") for fuente in resultado["fuentes"]
        ):
            raise RuntimeError("El agente documental devolvió una ficha ficticia.")
    tipo, eventos = solicitar(base, "/api/consultar/stream", casos[0][0])
    if (
        "text/event-stream" not in tipo
        or "event: resultado" not in eventos
        or "event: fin" not in eventos
    ):
        raise RuntimeError("El contrato SSE quedó incompleto.")
    print(
        f"Corpus documental verificado en {base}"
        if documental
        else f"Demo verificada en {base}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--corpus", action="store_true")
    args = parser.parse_args()
    url = urlparse(args.url)
    loopback = url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")
    if not loopback and (url.scheme != "https" or not url.hostname):
        parser.error("Usa HTTPS o la dirección local de la prueba.")
    if url.path not in ("", "/") or url.query or url.fragment or url.username:
        parser.error("Indica solo el origen de la demo.")
    comprobar(args.url.rstrip("/"), exigir_corpus=args.corpus)


if __name__ == "__main__":
    main()
