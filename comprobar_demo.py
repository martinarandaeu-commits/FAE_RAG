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


def solicitar(base: str, ruta: str, pregunta: str | None = None) -> tuple[str, str]:
    datos = json.dumps({"pregunta": pregunta}).encode() if pregunta else None
    req = Request(base + ruta, data=datos, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as respuesta:
        return respuesta.headers["Content-Type"], respuesta.read().decode("utf-8")


def comprobar(base: str) -> None:
    _, salud = solicitar(base, "/api/salud")
    estado = json.loads(salud)
    if estado.get("modo") != "demo":
        raise RuntimeError("El sitio no se identificó como demostración.")
    _, html = solicitar(base, "/")
    _, ayuda = solicitar(base, "/api/ayuda")
    if "Ayuda inmediata" not in html or not json.loads(ayuda)["demo"]:
        raise RuntimeError("El sitio no ofrece los controles previstos de la demo.")
    if estado.get("portal"):
        _, pantalla = solicitar(base, "/portal")
        _, consentimiento = solicitar(base, "/api/portal/consentimiento")
        if "Portal FAE" not in pantalla or not json.loads(consentimiento).get("demo"):
            raise RuntimeError("La ruta pública del portal no está disponible.")
    for pregunta, nivel, modo in CASOS:
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
    tipo, eventos = solicitar(base, "/api/consultar/stream", CASOS[0][0])
    if (
        "text/event-stream" not in tipo
        or "event: resultado" not in eventos
        or "event: fin" not in eventos
    ):
        raise RuntimeError("El contrato SSE quedó incompleto.")
    print(f"Demo verificada en {base}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    url = urlparse(args.url)
    loopback = url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")
    if not loopback and (url.scheme != "https" or not url.hostname):
        parser.error("Usa HTTPS o la dirección local de la prueba.")
    if url.path not in ("", "/") or url.query or url.fragment or url.username:
        parser.error("Indica solo el origen de la demo.")
    comprobar(args.url.rstrip("/"))


if __name__ == "__main__":
    main()
