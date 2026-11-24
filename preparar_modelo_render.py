"""Preparar E5 cuantizado en el build de Render y mapear su vocabulario."""

import argparse
from hashlib import file_digest
from pathlib import Path
from shutil import copyfileobj
from urllib.request import urlopen

ORIGEN = (
    "https://huggingface.co/Xenova/multilingual-e5-base/resolve/"
    "d59ab9ac3405fabf723089ec5577010211014c99/"
)
ARCHIVOS = {
    "onnx/model_quantized.onnx": (
        "df7a9a29309e3ad491e1783adf8baee710262cc06079c7cbab63c630277fac94"
    ),
    "tokenizer.json": (
        "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626"
    ),
}


def huella(ruta: Path) -> str:
    with ruta.open("rb") as archivo:
        return file_digest(archivo, "sha256").hexdigest()


def descargar(directorio: Path, nombre: str, esperado: str) -> Path:
    ruta = directorio / Path(nombre).name
    if ruta.is_file() and huella(ruta) == esperado:
        return ruta
    temporal = ruta.with_suffix(".part")
    try:
        with (
            urlopen(ORIGEN + nombre, timeout=90) as respuesta,
            temporal.open("wb") as f,
        ):
            copyfileobj(respuesta, f, 1024 * 1024)
        if huella(temporal) != esperado:
            raise ValueError(
                f"El archivo de E5 no coincide con la revisión fijada: {nombre}"
            )
        temporal.replace(ruta)
    finally:
        temporal.unlink(missing_ok=True)
    return ruta


def preparar(directorio: Path) -> None:
    import onnx
    from onnx import TensorProto, helper

    directorio.mkdir(parents=True, exist_ok=True)
    modelo_ruta = descargar(
        directorio, "onnx/model_quantized.onnx", ARCHIVOS["onnx/model_quantized.onnx"]
    )
    descargar(directorio, "tokenizer.json", ARCHIVOS["tokenizer.json"])
    modelo = onnx.load_model(modelo_ruta)
    grafo = modelo.graph
    nombre_peso = "embeddings.word_embeddings.weight_quantized"
    peso = next(p for p in grafo.initializer if p.name == nombre_peso)
    gather = next(n for n in grafo.node if nombre_peso in n.input)
    if (
        peso.data_type != TensorProto.UINT8
        or tuple(peso.dims) != (250002, 768)
        or gather.op_type != "Gather"
        or list(gather.input) != [nombre_peso, "input_ids"]
    ):
        raise ValueError("La revisión del modelo no tiene el vocabulario esperado.")
    # El vocabulario se lee por filas; ORT conserva el resto del grafo sin cambios.
    nombre_entrada = gather.output[0]
    (directorio / "vocabulario.uint8").write_bytes(peso.raw_data)
    grafo.initializer.remove(peso)
    grafo.node.remove(gather)
    grafo.input.append(
        helper.make_tensor_value_info(
            nombre_entrada, TensorProto.UINT8, ["batch_size", "sequence_length", 768]
        )
    )
    onnx.checker.check_model(modelo)
    onnx.save_model(modelo, directorio / "e5_consulta.onnx")
    modelo_ruta.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directorio", type=Path, default=Path(".modelos_render"))
    preparar(parser.parse_args().directorio)


if __name__ == "__main__":
    main()
