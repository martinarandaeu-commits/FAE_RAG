# Asistente FAE

El agente carga 4.671 vectores E5 de 768 dimensiones desde
`corpus/vectorizaciones_fae_e5.json.gz`. PostgreSQL almacena los fragmentos
y sus metadatos JSONB, con índices HNSW y GIN. El chat combina búsqueda
semántica y textual, devuelve extractos con citas, se abstiene si falta
evidencia y deriva los casos urgentes.

## Solemne II

La matriz original está en `data/`. Para reproducir el preprocesamiento de
las 105 referencias y comprobar sus cinco categorías, ejecuta:

```sh
python -m pip install -r requirements-solemne.txt
python pipeline_rag.py --modo validar
```

`02_esquema_local.sql` documenta la colección E5 local. En Render,
`fae_rag/corpus_render.py` prepara `fae_corpus.vectores` y carga el JSON
de forma automática. El corpus incluye 105 referencias bibliográficas,
4.535 fragmentos de URL y 31 fragmentos suplementarios.

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

## Render

El Blueprint `render.yaml` instala las dependencias, prepara el modelo E5
compacto y configura `DATABASE_URL` y `FAE_CORPUS_JSON`. En el primer
arranque el agente carga el corpus. Los arranques posteriores reutilizan
el índice si el JSON conserva la misma huella.

Después del despliegue, usa `python comprobar_demo.py URL --corpus` para
verificar que el enlace devuelve citas del corpus documental, permite
probar la abstención y expone la ruta de derivación.

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
