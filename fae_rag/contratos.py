"""Contratos para sustituir servicios externos por dobles en las pruebas."""

from typing import Any, Protocol, TypedDict


class Documento(TypedDict):
    """Evidencia recuperada con identificador y procedencia."""

    chunk_id: str
    categoria: str
    seccion: str
    fuente: str
    contenido: str
    metadata: dict[str, Any]
    similitud: float


class Recuperador(Protocol):
    """Puerto para recuperar evidencia, independiente del motor de búsqueda."""

    def __call__(
        self, pregunta: str, categoria: str | None = None, limite: int = 3
    ) -> list[Documento]: ...


class Generador(Protocol):
    """Puerto de generación fundamentada, independiente del proveedor."""

    def __call__(self, pregunta: str, documentos: list[Documento]) -> str: ...
