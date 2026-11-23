# Estado del producto FAE

El portal local se abre en `http://127.0.0.1:8010/portal`. Usa una base
de demostración separada y cuentas ficticias. El agente documental E5
conserva su índice de 4.671 vectores en la base original.

| Requisitos | Implementación y verificación | Falta para el piloto |
| --- | --- | --- |
| HU-01 a HU-06 | Chat con extractos y fuentes enlazadas, contexto reciente, abstención y temas sugeridos. El flujo se probó con HTTP y PostgreSQL. | Validar respaldo por afirmación, pertinencia y latencia con el conjunto acordado. |
| HU-07, HU-51 a HU-53 | Valoración binaria y métricas anónimas semanales, panel por rol y CSV. Se ocultan grupos de menos de cinco. | Cola de revisión de respuestas con anonimización validada y agrupación temática. |
| HU-08 a HU-11 | Clasificación antes de recuperar y ayuda independiente de Gemini. Canales configurables por región y rol. Probados 51 casos propios, incluidos 17 rojos, luego de ajustar tres frases. | Validación con casos independientes y canales aprobados por el Observatorio. |
| HU-12 a HU-15 | Borrador editable, copiable y compartible por correo o WhatsApp desde la cuenta asociada. Se requiere acción del usuario. | Resumen automático anonimizado a partir del relato y validación del protocolo de contacto. |
| HU-16 a HU-20 | Modo abierto sin almacenamiento individual. Directorio regional, enlaces oficiales de postulación y materiales que publica curaduría. | Incorporar programas y testimonios autorizados. |
| HU-21 a HU-31 | Invitaciones únicas, verificación ficticia, consentimiento, sesiones, recuperación, perfil, línea de tiempo, historial cifrado, exportación, borrado y reasociación. Se verificaron permisos de titular y desvinculación en PostgreSQL. | Probar el correo real, aprobar el consentimiento y confirmar relación responsable y retención de respaldos. |
| HU-32 a HU-35 | Interfaz móvil, extractos desplegables, lectura en voz local y materiales. El recorrido de administración, ayuda y ruta roja pasó en Edge a 360 px. | Prueba completa de accesibilidad con usuarios, dictado local y tarjetas específicas para procedimientos. |
| HU-36 a HU-41 | Curaduría de PDF, DOCX, TXT y texto revisado. La nueva versión retira la anterior. El portal documental fragmenta y vectoriza con E5 al publicar, mientras la demo de Render recupera por texto. | Falta cerrar la revisión institucional de respuestas y validar la operación de curaduría con contenido real. |
| HU-42 a HU-48 | Alta de duplas y personal, TOTP, permisos, invitaciones, baja, contacto, ajustes y auditoría técnica. Probados 4 roles e historial aislado. | Confirmar responsables, suplencias, recuperación de MFA y operación del registro en producción. |
| HU-49 y HU-50 | Prueba reproducible de semáforo, evaluación exploratoria E5 y señal de salud por API. | Ejecutar el conjunto de evaluación del Observatorio, pruebas de concurrencia y disponibilidad en Render. |
| HU-54 | Calcula distancia en el navegador desde lugares publicados y ofrece filtro manual por región y comuna. | Cargar y validar horarios y coordenadas de urgencias reales. [Fuente candidata DEIS](https://deis.minsal.cl/sistemas/). |
| COR-01 a COR-11 | Cinco categorías, 105 referencias, 67 URL con texto y un artículo suplementario con páginas, DOI y licencia. | Completar prioridad y vigencia estructurada del resto del corpus y las publicaciones solicitadas a la contraparte. |

## Pruebas repetibles

- `python -m unittest discover` prueba el agente y la API.
- `python validar_portal_local.py` crea una base temporal y prueba cuentas,
  verificación, roles, consentimiento, MFA, historial, exportación, borrado,
  reasociación, rechazo de otro origen y publicación.
- `python validar_portal_local.py --indice-e5` comprueba también la ingesta,
  recuperación híbrida y exclusión de versiones retiradas en PostgreSQL.
- `python evaluar_semaforo_sintetico.py` escribe el informe de las 51 frases
  internas en `resultados/evaluacion_semaforo_sintetico.json`.
- `python comprobar_demo.py URL` prueba la instancia desplegada con
  consultas ficticias. Verifica salud, portal, citas, derivación y eventos.

## Fuentes que faltan

El capítulo *Familias de acogida: un país que se forma para cuidar y
proteger* tiene su resumen en el índice local. La publicación
*De familias de acogida a familias de adopción* ya aporta 31 fragmentos
con [licencia CC BY 4.0](https://revistas.upsa.es/index.php/familia/Copyright_Licensing).
Faltan el capítulo completo de 2024, el documento sobre transición
respetuosa y el estudio de familias sin vínculo previo.

## Estado de publicación

El paquete de Render contiene la demo con datos ficticios. Está pendiente
crear el repositorio remoto, vincular GitHub a Render y confirmar la URL
con una prueba HTTP. No hay credenciales de publicación en este espacio.
