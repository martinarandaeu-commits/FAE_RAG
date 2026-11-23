"""Contrato de registro público con persistencia y envío de correo aislados."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fae_rag.portal_auth import CONSENTIMIENTO_VERSION, HASHEADOR
from fae_rag.portal_cuentas import router_cuentas


class RegistroPublicoTest(unittest.TestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.cursor.fetchone.return_value = None
        self.transaccion = self.add_patch("transaccion")
        self.transaccion.return_value.__enter__.return_value = self.cursor
        self.limitar = self.add_patch("limitar")
        self.token = self.add_patch("token_temporal", return_value="v" * 43)
        self.enviar = self.add_patch(
            "enviar_token",
            return_value={"estado": "prueba", "token_prueba": "v" * 43},
        )
        self.client = self.cliente(demo=True)
        self.addCleanup(self.client.close)
        self.datos = {
            "correo": "familia@example.test",
            "clave": "UnaClaveDePrueba123",
            "confirmar_clave": "UnaClaveDePrueba123",
            "consentimiento": True,
            "version": CONSENTIMIENTO_VERSION,
        }

    def add_patch(self, nombre, **kwargs):
        parche = patch(f"fae_rag.portal_cuentas.{nombre}", **kwargs)
        resultado = parche.start()
        self.addCleanup(parche.stop)
        return resultado

    @staticmethod
    def cliente(demo):
        app = FastAPI()
        app.include_router(router_cuentas(demo))
        return TestClient(app)

    def registrar(self, **cambios):
        return self.client.post("/api/portal/registrar", json=self.datos | cambios)

    def inserciones(self):
        return [
            llamada.args
            for llamada in self.cursor.execute.call_args_list
            if "INSERT INTO fae_portal.usuarios" in llamada.args[0]
        ]

    def test_crea_familia_pendiente_con_clave_hasheada_y_consentimiento(self):
        respuesta = self.registrar(correo="  FAMILIA@EXAMPLE.TEST  ")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()["token_prueba"], "v" * 43)
        [(sql, valores)] = self.inserciones()
        uid, correo, clave, version = valores
        self.assertEqual(correo, "familia@example.test")
        self.assertEqual(version, CONSENTIMIENTO_VERSION)
        self.assertNotEqual(clave, self.datos["clave"])
        self.assertTrue(HASHEADOR.verify(clave, self.datos["clave"]))
        self.assertIn("'familia'", sql)
        self.assertNotIn("verificado", sql)
        self.assertNotIn("dupla", sql)
        self.token.assert_called_once_with(self.cursor, uid, "verificar", 60)
        self.enviar.assert_called_once_with(correo, "verificar", "v" * 43, True)
        self.assertNotIn("set-cookie", respuesta.headers)

    def test_no_permite_que_el_cliente_asigne_permisos_o_dupla(self):
        for campo, valor in [
            ("rol", "admin"),
            ("dupla", "cualquier-dupla"),
            ("verificado", True),
            ("activo", True),
        ]:
            with self.subTest(campo=campo):
                self.assertEqual(self.registrar(**{campo: valor}).status_code, 422)
        self.transaccion.assert_not_called()
        self.enviar.assert_not_called()

    def test_rechaza_claves_distintas(self):
        respuesta = self.registrar(confirmar_clave="OtraClaveDePrueba123")
        self.assertEqual(respuesta.status_code, 422)
        self.transaccion.assert_not_called()
        self.enviar.assert_not_called()

    def test_rechaza_claves_fuera_del_largo_permitido(self):
        for clave in ("corta", "a" * 129):
            with self.subTest(largo=len(clave)):
                self.assertEqual(
                    self.registrar(clave=clave, confirmar_clave=clave).status_code, 422
                )
        self.transaccion.assert_not_called()

    def test_exige_consentimiento_y_version_actual(self):
        self.assertEqual(self.registrar(consentimiento=False).status_code, 422)
        self.assertEqual(self.registrar(version="otra-version").status_code, 422)
        self.transaccion.assert_not_called()

    def test_rechaza_correo_invalido_y_correo_real_en_demo(self):
        for correo in ("sin-arroba", "familia@example.com"):
            with self.subTest(correo=correo):
                self.assertEqual(self.registrar(correo=correo).status_code, 422)
        self.transaccion.assert_not_called()
        self.enviar.assert_not_called()

    def test_no_reemplaza_una_cuenta_existente(self):
        self.cursor.fetchone.return_value = {"existe": 1}
        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(self.inserciones(), [])
        self.token.assert_not_called()
        self.enviar.assert_not_called()
        self.assertFalse(
            any("UPDATE" in c.args[0] for c in self.cursor.execute.call_args_list)
        )

    def test_limita_intentos_antes_de_crear_una_cuenta(self):
        self.limitar.side_effect = HTTPException(429, "Demasiados intentos.")
        self.assertEqual(self.registrar().status_code, 429)
        self.transaccion.assert_not_called()
        self.enviar.assert_not_called()

    def test_modo_real_solicita_correo_sin_exponer_el_token(self):
        self.enviar.return_value = {"estado": "correo_solicitado"}
        datos = self.datos | {"correo": "familia@example.com"}
        with self.cliente(demo=False) as cliente:
            respuesta = cliente.post("/api/portal/registrar", json=datos)
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json(), {"estado": "correo_solicitado"})
        self.enviar.assert_called_once_with(
            "familia@example.com", "verificar", "v" * 43, False
        )
        self.assertNotIn("set-cookie", respuesta.headers)


if __name__ == "__main__":
    unittest.main()
