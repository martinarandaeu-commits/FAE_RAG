"""Entrada compatible para validar o insertar las referencias FAE."""

from fae_rag.cli import main_referencias as main
from fae_rag.configuracion import ARCHIVO, BASE, HOJAS
from fae_rag.matrices import construir_chunk, procesar_matrices_rag
from fae_rag.repositorio import insertar_vectores
from fae_rag.taxonomia import CATEGORIAS, categoria_por_contexto
from fae_rag.texto import limpiar_texto, normalizar

if __name__ == "__main__":
    main()
