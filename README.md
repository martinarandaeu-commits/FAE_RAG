# Demo FAE en Render

La demo usa FastAPI, una base PostgreSQL separada y cinco fichas sintéticas.
Asigna el nivel de derivación, muestra extractos y permite probar la abstención.
El servicio web usa recuperación textual. El agente documental completo,
con E5 y pgvector, sigue disponible en el computador.
El mismo Blueprint habilita el portal de familia y el backoffice de prueba.

## Revisión en este computador

Ejecuta `python iniciar_portal_demo.py` y abre `http://127.0.0.1:8010/portal`.
Se usa la base separada `fae_demo_portal_local`. La cuenta de administración
de prueba y el secreto de cifrado se generan en `.env.portal`. Usa el correo
y la clave inicial de ese archivo e inscribe la cuenta en una aplicación TOTP.
Para las cuentas ficticias se valida el correo dentro del navegador con un
token de prueba. Esta operación requiere que el correo termine en `.test`.

## Registro de familias

En `/portal`, selecciona **Crear cuenta**. El registro solicita correo,
contraseña de al menos 12 caracteres, confirmación y consentimiento.
La cuenta se habilita para iniciar sesión después de verificar el correo.
En la demo usa una dirección ficticia como `familia@example.test` y pulsa
**Verificar correo de prueba** para completar ese paso en el navegador.

El registro crea una cuenta de familia sin dupla asociada. Puedes vincularla
más adelante con una invitación de tu equipo. El alta de personal continúa
mediante invitaciones de administración o curaduría.

Para ejecutar las pruebas del registro instala `requirements-dev.txt` y usa
`python -m unittest discover -s tests -v`. Las pruebas aíslan la persistencia
y el envío de correo; no requieren una base de datos ni envían mensajes.

## Configuración de administración en Render

El Blueprint genera `FAE_PORTAL_SECRETO` en Render. Para habilitar el primer
administrador define `FAE_ADMIN_CORREO` con una dirección ficticia `.test` y
`FAE_ADMIN_CLAVE` con una contraseña única en **Environment**. Después de
inscribir TOTP y verificar el acceso, retira la contraseña de arranque de
la configuración. El hash de la cuenta se conserva en PostgreSQL.

La configuración del portal documental para datos reales requiere el
backend local E5. La verificación y recuperación por correo admiten
Resend por HTTPS, con `FAE_URL_PUBLICA`, `FAE_RESEND_API_KEY` y
`FAE_CORREO_REMITENTE`. También existe la salida SMTP para instalaciones
que permitan ese tráfico. La demo de Render valida solamente correos ficticios.
En el portal documental, la publicación de documentos y guías genera
fragmentos E5 en el esquema `fae_portal`. La búsqueda descarta borradores y
versiones retiradas, y conserva los índices originales en `public`.

## Repositorio privado

Genera el ZIP de publicación con `python preparar_render.py`. El paquete
contiene solo los archivos necesarios para que Render instale y ejecute la
demo. Mantén el repositorio privado y coloca `render.yaml` en la raíz.

Para publicar con acceso delegado, guarda `GITHUB_TOKEN` localmente en
`.env.deploy` y ejecuta `python preparar_render.py --github`. El token debe
poder crear repositorios privados y escribir contenido. El comando comprueba
que el repositorio sea privado y que su único archivo inicial sea el README
de GitHub antes de subir el código. Revoca el token cuando termine la publicación.

## Render

1. En Render, conecta GitHub con acceso al repositorio privado de la demo.
2. Abre **New → Blueprint** y selecciona el repositorio. Revisa que el
   servicio web y PostgreSQL indiquen el plan `free` antes de aplicar.
3. Espera a que el servicio esté activo. Render proporciona `DATABASE_URL`
   mediante la conexión interna de su PostgreSQL. La aplicación carga sus
   fichas de demostración de forma idempotente.
4. Ejecuta `python comprobar_demo.py URL` para probar el chat, las fuentes,
   la derivación, la abstención y la respuesta progresiva.

El servicio gratuito puede suspenderse cuando está inactivo y la base
gratuita vence a los 30 días. [Documentación](https://render.com/docs/free).

La interfaz permite evaluar de forma binaria una respuesta con fuentes.
Las métricas guardan contadores semanales, sin texto de consultas ni votos
individuales. El panel está disponible para curaduría y administración.
El acceso técnico alternativo se habilita con una clave local
`FAE_METRICAS_CLAVE`; la entrega se solicita en `/api/demo/metricas` con la
cabecera `X-FAE-Demo-Key`. Los grupos de menos de cinco quedan ocultos.

## Canales de ayuda

Publica los canales aprobados como curador. Como respaldo, configura
`FAE_CANALES_APROBADOS` con la ruta a un JSON institucional. El
formato es una lista de objetos con `nombre`, `telefono` y, opcionalmente,
`uso`. El orden de los elementos es el orden que ve la familia. Mientras la
lista esté vacía, la aplicación indica que faltan contactos configurados.

## Paso a piloto

Antes de publicar con familias reales hacen falta canales y criterios de
riesgo aprobados, el conjunto de evaluación de aceptación, fuentes con
permiso de uso y una decisión institucional sobre acceso, conservación
y tratamiento de datos. Consulta [ALCANCE_FAE.md](ALCANCE_FAE.md).
