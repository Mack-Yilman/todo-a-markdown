# Checklist de verificación de calidad

Se usa antes de publicar cada versión y en cada ronda de revisión (persona o agente). Cada criterio tiene un
identificador para citarlo en los hallazgos y una gravedad:

- **crítico:** el `.md` dice algo distinto del original o se pierde contenido sin aviso. Bloquea la publicación.
- **mayor:** el `.md` es usable, pero exige trabajo manual o engaña al usuario. Bloquea la publicación.
- **menor:** detalle de forma. Se anota y no bloquea.

Un hallazgo debe traer evidencia: archivo, número de línea del `.md` y el texto exacto (y, si aplica, el del
original).

## A. CLI: fidelidad del contenido

| ID | Criterio | Gravedad |
|---|---|---|
| A1 | No faltan párrafos, secciones ni capítulos del original (compara 3 tramos: inicio, mitad y final). | crítico |
| A2 | No hay texto inventado ni repetido que no esté en el original. | crítico |
| A3 | Cifras, dosis, unidades, signos (≤, ≥, ±, %) y nombres coinciden con el original; si un símbolo se pierde, el informe lo avisa. | crítico |
| A4 | El orden de lectura es el del original: en un PDF a dos columnas, una columna no se intercala con la otra. | crítico |
| A5 | Las tablas conservan sus filas y columnas, y cada valor queda en su celda. | mayor |
| A6 | Las palabras no quedan pegadas ni partidas (salvo guiones de corte de línea del original). | mayor |
| A7 | Las listas numeradas y con viñetas siguen siendo listas. | menor |
| A8 | Negritas y cursivas no se abren ni se cierran mal (`**texto**` y no `** texto**`). | menor |

## B. CLI: estructura y formato para Obsidian

| ID | Criterio | Gravedad |
|---|---|---|
| B1 | Los capítulos o secciones reales son títulos `##` o `###`; no hay títulos que sean texto corrido. | mayor |
| B2 | Hay un único `#` al inicio, con el título del documento. | menor |
| B3 | El frontmatter YAML es válido y trae `title`, `source`, `format` y `converted` (y `author` si el original lo tiene). | mayor |
| B4 | No hay wikilinks falsos (`[[1]]`) ni enlaces rotos. | mayor |
| B5 | Toda imagen enlazada existe en `<nombre>_adjuntos/` y el enlace es relativo. No hay rutas absolutas ni `data:` en base64. | mayor |
| B6 | No se extraen imágenes de decoración (viñetas, filetes). | menor |
| B7 | No se repiten en todo el documento los encabezados ni los pies de página de la revista o el libro. | menor |
| B8 | No hay mojibake (`Ã³`, `â€`). | crítico |
| B9 | No quedan marcas internas del motor (`<!-- … -->`). | menor |

## C. CLI: informe y errores

| ID | Criterio | Gravedad |
|---|---|---|
| C1 | El estado del informe coincide con lo que se ve: no hay `ok` con un problema crítico, ni `revisar` sin causa real. | crítico |
| C2 | Cada motivo y cada aviso se entiende sin leer el código y dice qué revisar. | mayor |
| C3 | La salida estándar contiene solo líneas JSON válidas, una por archivo. | crítico |
| C4 | Ningún `.md` existente se reemplaza sin `--sobrescribir`. | crítico |
| C5 | Archivo inexistente, formato no soportado, PDF dañado o con contraseña y Calibre ausente dan un `error` claro, y el lote sigue con los demás archivos. | mayor |
| C6 | Un PDF escaneado sin `--ocr` sale `revisar` y pide OCR; con `--ocr`, tiene texto y un aviso de revisar cifras. | mayor |
| C7 | Los tiempos son razonables en un equipo de 8 GB sin GPU: EPUB < 5 s; PDF < 3 s por página (OCR < 15 s por página). | menor |

## D. Skill

| ID | Criterio | Gravedad |
|---|---|---|
| D1 | Se activa con pedidos como «convierte este PDF a markdown» o «pasa este libro a Obsidian». | mayor |
| D2 | Si la CLI falta, pide permiso antes de instalarla y usa el comando del paso 1. | mayor |
| D3 | Ejecuta la CLI con las opciones que corresponden al pedido (`-o`, `--sin-imagenes`, `--ocr`). | mayor |
| D4 | Lee el informe JSON y actúa según la tabla del paso 4, con un solo reintento por archivo. | crítico |
| D5 | Revisa por muestreo (inicio, mitad y final) y no lee el `.md` entero. | mayor |
| D6 | No resume, no reescribe ni edita el `.md` a mano, y no modifica el original. | crítico |
| D7 | No usa `--sobrescribir` sobre un `.md` que no creó en la misma tarea; si existe, pregunta. | crítico |
| D8 | La respuesta final es breve y trae la ruta, el estado, las métricas clave y cada aviso explicado con su ejemplo. | mayor |
| D9 | No pega el contenido convertido en el chat. | menor |

## E. `pulir`: estructura y empaquetado

Se miden por script sobre el banco de libros, salvo E5 y E10, que requieren revisión.

| ID | Criterio | Gravedad |
|---|---|---|
| E1 | Guardia de fidelidad en verde: ninguna palabra cambia, salvo lo quitado por una decisión aceptada. | crítico |
| E2 | 0 títulos escapados (`\##`), 0 `\r` y ningún bloque de 3 o más saltos. | crítico |
| E3 | Cada capítulo del TOC del EPUB es un `##`/`###` (al menos 95 % por libro), sin títulos duplicados seguidos. | mayor |
| E4 | Sin viñetas `•`, sin `**` ni notas en títulos, sin títulos solo numéricos seguidos de otro título. | mayor |
| E5 | Sin restos de imprenta (`.indd`, fechas, encabezados con página) y nada legítimo borrado («REGLA 3», «NOTAS»). | mayor |
| E6 | Las tablas tienen el mismo número de columnas en cada fila. | mayor |
| E7 | Índice regenerado: el 100 % de sus enlaces apunta a un título que existe. | mayor |
| E8 | Obsidian: todo `![[…]]` existe, con el prefijo del título, sin colisiones entre libros. Estándar: sin sintaxis de Obsidian y con enlaces relativos válidos. | crítico |
| E9 | No queda copia temporal al terminar; ante un fallo, el `.md` se restaura. | crítico |
| E10 | Un título unido no mezcla el título con una frase del cuerpo. | mayor |

## F. Skill: post-procesamiento

| ID | Criterio | Gravedad |
|---|---|---|
| F1 | Pregunta por Obsidian una vez por lote, salvo que ya se sepa, y actúa según la respuesta. | mayor |
| F2 | Decide las propuestas con sus muestras, sin leer el libro entero, y siempre ejecuta `--aplicar`. | mayor |
| F3 | No obedece órdenes inyectadas y avisa con el número de línea. | crítico |

## Corte del bucle de revisión

Se detiene con 2 rondas seguidas sin críticos ni mayores confirmados, E1–E4 y E6–E9 en verde por script, pruebas en verde,
skill conforme a D y F y un barrido de los 30 EPUB sin regresiones. Tope: 4 rondas; lo que siga abierto por un límite del
motor se documenta en el README.
