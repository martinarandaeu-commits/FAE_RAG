"""Inferencia E5 de CPU para el despliegue documental."""

import os
from functools import lru_cache
from threading import Lock

from .configuracion import BASE

ENTRADA_VOCABULARIO = "/embeddings/word_embeddings/Gather_output_0_quantized"
FORMA_VOCABULARIO = (250002, 768)
_INFERENCIA = Lock()


@lru_cache(maxsize=1)
def crear_cliente():
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    directorio = BASE / os.getenv("FAE_MODELO_DIR", ".modelos_render")
    opciones = ort.SessionOptions()
    opciones.intra_op_num_threads = 1
    opciones.inter_op_num_threads = 1
    opciones.enable_cpu_mem_arena = False
    opciones.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    opciones.add_session_config_entry("session.disable_prepacking", "1")
    sesion = ort.InferenceSession(
        str(directorio / "e5_consulta.onnx"),
        sess_options=opciones,
        providers=["CPUExecutionProvider"],
    )
    vocabulario = np.memmap(
        directorio / "vocabulario.uint8",
        dtype=np.uint8,
        mode="r",
        shape=FORMA_VOCABULARIO,
    )
    tokenizador = Tokenizer.from_file(str(directorio / "tokenizer.json"))
    tokenizador.enable_truncation(max_length=512)
    return sesion, vocabulario, tokenizador


def generar_embedding(
    texto: str, cliente, tipo: str = "RETRIEVAL_QUERY"
) -> list[float]:
    import numpy as np

    if tipo != "RETRIEVAL_QUERY" or not texto.strip():
        raise ValueError("Consulta E5 inválida.")
    sesion, vocabulario, tokenizador = cliente
    tokens = tokenizador.encode("query: " + texto)
    ids = np.array([tokens.ids], dtype=np.int64)
    mascara = np.array([tokens.attention_mask], dtype=np.int64)
    with _INFERENCIA:
        salida = sesion.run(
            None,
            {
                "input_ids": ids,
                "attention_mask": mascara,
                ENTRADA_VOCABULARIO: vocabulario[ids],
            },
        )[0]
    vector = (salida * mascara[..., None]).sum(axis=1)[0] / mascara.sum()
    norma = np.linalg.norm(vector)
    if vector.shape != (FORMA_VOCABULARIO[1],) or not np.isfinite(norma) or norma == 0:
        raise ValueError("El modelo de consulta produjo un vector E5 inválido.")
    return (vector / norma).tolist()
