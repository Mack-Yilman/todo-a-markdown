---
name: todo-a-markdown
description: "Convierte libros y documentos (EPUB, PDF, DOCX, PPTX, XLSX, HTML, CSV, MOBI, AZW3, FB2) a Markdown limpio para Obsidian y para LLM con la CLI todo-a-markdown, y verifica la calidad de cada conversión antes de entregarla. Úsala cuando el usuario diga «convierte este PDF a markdown», «pasa este libro a Obsidian», «convierte este EPUB/Word/PowerPoint/Excel a .md», «quiero este paper en markdown», «extrae el texto de este documento a markdown» o «convierte todos los archivos de esta carpeta»."
license: AGPL-3.0-or-later
---

# todo-a-markdown

Tu trabajo es que el usuario reciba un `.md` **fiel al original** y sepa qué tan confiable es. Para eso manejas la CLI `todo-a-markdown`, lees su informe de calidad, corriges lo que se puede corregir con sus opciones y le dices con claridad lo que no.

## Reglas

- **No resumas, no reescribas, no traduzcas ni «mejores» el contenido convertido.** Si el usuario después quiere un resumen o apuntes, esa es otra tarea y se hace sobre el `.md` ya entregado.
- **No leas entero un `.md` largo.** Un libro tiene cientos de miles de caracteres. Revisa por muestreo (paso 5).
- **No modifiques el original** ni lo muevas.
- **No uses `--sobrescribir` para reemplazar un `.md` que no creaste en esta misma tarea:** puede tener notas del usuario. Si ya existe, pregúntale si lo reemplazas o si guardas en otra carpeta.
- **No edites el `.md` a mano para «arreglarlo».** Si el informe marca un problema que las opciones de la CLI no resuelven, lo informas.
- Pon entre comillas las rutas con espacios o tildes.
- Todo se procesa en el equipo del usuario: la CLI no envía nada a internet.

## 1. Preparar

1. Comprueba que la CLI está instalada: `todo-a-markdown --version`.
2. Si no lo está, **pide permiso al usuario** y luego instálala:
   - con uv: `uv tool install git+https://github.com/Mack-Yilman/todo-a-markdown`
   - con OCR para PDF escaneados: `uv tool install "todo-a-markdown[ocr] @ git+https://github.com/Mack-Yilman/todo-a-markdown"`
   - con Docling para papers a dos columnas (ocupa unos 1,6 GB; dilo al pedir permiso): `uv tool install --force "todo-a-markdown[docling] @ git+https://github.com/Mack-Yilman/todo-a-markdown"`. Para tener ambos extras, escribe `[ocr,docling]`.
   - sin uv: `python -m pip install --user git+https://github.com/Mack-Yilman/todo-a-markdown`
3. Decide el destino: si el usuario nombró una carpeta (por ejemplo, la de su vault), usa `-o "<carpeta>"`. Si no, la CLI guarda junto al original.

## 2. Convertir

| Si el pedido es… | Ejecuta |
|---|---|
| Un archivo | `todo-a-markdown "<archivo>"` |
| Varios archivos o una carpeta entera | `todo-a-markdown "<a>" "<b>"` o `todo-a-markdown "<carpeta>"` (sin subcarpetas) |
| Guardar en otra carpeta | agrega `-o "<carpeta>"` |
| Solo el texto, sin figuras | agrega `--sin-imagenes` |
| Un PDF escaneado (fotos de páginas) | agrega `--ocr` |
| Un paper o artículo a dos columnas, o el usuario pide máxima fidelidad en tablas | agrega `--motor docling` |

- **Tiempos orientativos:** EPUB y Office, segundos; PDF, 1–2 s por página; PDF con OCR, unos 8 s por página; PDF con Docling, unos 10 s por página. Si el lote es grande (más de 100 páginas de PDF o más de 10 archivos), ejecútalo en segundo plano si tu entorno lo permite y avisa al usuario de cuánto tardará.
- Formatos MOBI, AZW, AZW3 y FB2 necesitan Calibre instalado.

## 3. Leer el informe

Por cada archivo, la CLI imprime **una línea JSON** en la salida estándar. Las líneas legibles van a la salida de errores.

| Campo | Qué es |
|---|---|
| `estado` | `ok`, `revisar` o `error` |
| `salida` | ruta del `.md`; las imágenes van en `<nombre>_adjuntos/` |
| `motivos` | problemas que dejan el estado en `revisar` |
| `avisos` | cosas que el usuario debe saber, aunque el estado sea `ok` |
| `metricas` | palabras, `lineas` del `.md`, `ratio` contra el original, títulos (`h1`, `h2`, `h3`), imágenes, páginas, segundos |
| `error` | si `estado` es `error`, la causa |

El código de salida es 0 si todo está `ok`, 1 si hay algún `revisar` y 2 si hay algún `error`.

## 4. Actuar según el informe

Cada motivo empieza con una clave (`escaneado:`, `texto_perdido:`…). Reintenta **una sola vez** por archivo. Al reintentar, usa `--sobrescribir`, porque reemplazas el `.md` que acabas de crear.

| Si ves… | Haz esto |
|---|---|
| `escaneado` | Reintenta con `--ocr`. Si responde «no hay motor de OCR instalado», pide permiso para reinstalar con el extra `[ocr]` (paso 1). |
| `dos_columnas` | Si el PDF tiene hasta 50 páginas, reintenta con `--motor docling`. Si responde «Docling no está instalado», pide permiso para instalarlo (paso 1). Con más de 50 páginas, o si el usuario no quiere instalarlo, revisa el orden de lectura en el paso 5 y dile qué tramos mezclan columnas. |
| `texto_perdido` en un PDF con `paginas_sin_texto` > 0 | Reintenta con `--ocr`. |
| `texto_perdido` en otro caso | No reintentes. Compara en el paso 5 dónde falta texto e infórmalo con el porcentaje. |
| `imagenes_rotas` | Reintenta una vez. Si sigue, ofrece `--sin-imagenes`. |
| `mojibake` | Informa que hay caracteres mal decodificados y cita un ejemplo del `.md`. No lo corrijas a mano. |
| `wikilinks_falsos` | Es un fallo de la CLI: informa el número y el archivo. |
| `sin_titulos` | El original no marca sus títulos (frecuente en PDF). Informa que la navegación en Obsidian será pobre. No inventes títulos. |
| aviso `simbolos_ilegibles` | Dile al usuario que el original guarda símbolos como ≤, ≥ o ± sin código legible, que salen como �, y cita el ejemplo del aviso. Que revise esas cifras contra el PDF. |
| `ocr` | No reintentes: es el resultado del OCR. En el paso 5 revisa el doble de tramos y anota cada línea con basura, texto cortado o columnas mezcladas. Dile al usuario que verifique cifras, dosis y nombres contra el original. |
| aviso `formulas_omitidas` | Dile cuántas ecuaciones quedaron marcadas como «[fórmula no convertida]» y que las consulte en el original. |
| aviso `lineas_repetidas` | Menciona la línea repetida (suele ser el encabezado o el pie de página de la revista). |
| aviso `saltos_de_nivel`, `paginas_sin_texto` o `texto_duplicado` | Menciónalo en una línea. |
| `error`: «ya existe un .md» | Pregunta si se reemplaza o si se guarda en otra carpeta. |
| `error`: archivo inexistente, formato no soportado, contraseña o Calibre ausente | Explica la causa con el texto del error y qué puede hacer el usuario. |
| `error`: otro | Informa el texto del error tal cual. |

## 5. Revisar por muestreo

El informe mide; tú confirmas que se lee bien. Para cada `.md` (en lotes de más de 5 archivos: todos los `revisar` y dos `ok`):

1. Si el `.md` tiene menos de 150 `lineas`, léelo entero. Si no, lee unas 40 líneas tras el frontmatter, otras 40 desde la mitad (`lineas` / 2) y las últimas 40, por número de línea.
2. Comprueba:
   - el texto se lee seguido, sin palabras pegadas ni frases cortadas;
   - en un PDF a dos columnas, una columna no se mezcla con la otra;
   - los títulos corresponden a capítulos o secciones reales;
   - las tablas tienen las filas y columnas alineadas;
   - si hay imágenes, los enlaces apuntan a `<nombre>_adjuntos/`.
3. Si encuentras un problema que el informe no marcó, inclúyelo en tu respuesta con el número de línea.

## 6. Responder

Entrega en pocas líneas, sin pegar el contenido convertido:

- la ruta de cada `.md` y su estado tras los reintentos;
- palabras, capítulos (`h2`) e imágenes, en una línea;
- cada aviso o problema en lenguaje simple, con el ejemplo concreto y qué revisar en el original;
- si algo quedó sin resolver, qué opción le queda (otra carpeta, `--sin-imagenes`, instalar OCR o Calibre).

Con varios archivos, usa una tabla de hasta 4 columnas: archivo, estado, palabras y avisos.
