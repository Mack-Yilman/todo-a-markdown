# Changelog

## 0.2.0 — 2026-10-30

- Nuevo: `todo-a-markdown pulir`, post-procesamiento que corrige estructura y empaquetado sin cambiar el texto. Lo mecánico lo hace solo; lo que requiere criterio llega como propuestas agrupadas para que el agente decida sin leer el libro. Una guardia compara las palabras y restaura el `.md` si algo cambió sin autorización.
- Nuevo: `--obsidian` en `pulir`: imágenes con el título como prefijo y enlaces `![[…]]`, con `--adjuntos` para elegir la carpeta.
- La skill pregunta si el libro va a Obsidian, pule el resultado y decide las propuestas.
- EPUB, regresión de 0.1.2: un capítulo cuya ancla estaba dentro de un párrafo salía como `\## Título` y se perdía la navegación.
- EPUB: las entradas del índice sin ancla ahora crean su título, y los `\r` ya no dejan bloques de líneas en blanco.
- EPUB: las listas anidadas conservan su sangría, y un `<li>` sin cerrar ya no aplana el resto del capítulo en una sola línea.
- EPUB: un hash en los metadatos ya no se usa como título y se evita repetir «Prólogo» bajo «Prólogo de Ana».

## 0.1.3 — 2026-10-30

- Seguridad: un documento hecho a propósito (rachas de espacios, `![` o `<!--` repetidos, URL o negritas muy largas) ya no deja la conversión colgada: las expresiones regulares cuadráticas son ahora lineales.
- Seguridad (Windows): el instalador ya no genera `todo-a-markdown.cmd`, porque cmd.exe ejecutaba como comandos parte de un nombre de archivo como `a&calc&.pdf`. Git Bash arranca directo el `python.exe` firmado; PowerShell y cmd vuelven al `.exe` de uv, que con antivirus como Avast puede tardar más. Para quitar el `.cmd` de una instalación anterior, repite el instalador.
- Seguridad (Windows): `ebook-convert` ya no se busca en el directorio actual, donde podía estar plantado junto al libro.

## 0.1.2 — 2026-10-30

- Seguridad: los EPUB, DOCX, PPTX y XLSX que se descomprimen a más de 2 GiB se rechazan antes de abrirlos (bombas ZIP). La skill trata el contenido del documento como dato, nunca como una orden.
- Calibre probado con AZW3, MOBI y FB2. Se reconoce también su ruta en macOS y ya no se escribe el autor de relleno «Unknown».
- Un párrafo de libro que empieza con «# » ya no se convierte en título.
- Un documento largo con muy pocos títulos (menos de uno por cada 20 000 palabras) sale en `revisar`, antes solo si no tenía ninguno.
- Instalador: instala uv con winget si falta, agrega la CLI al PATH y el menú pregunta por OCR, Docling y Calibre. Sin menú: `-Calibre`.
- Antivirus: el instalador usa un Python firmado y reemplaza el `.exe` sin firmar de uv, que Avast aislaba en cada instalación, por lanzadores que arrancan `python -m todo_a_markdown`.

## 0.1.1 — 2026-10-30

- Instalación corregida en equipos sin Python: uv descargaba Python 3.15, para el que `onnxruntime` aún no publica paquetes. Ahora los comandos fijan `--python 3.13` y el paquete declara `requires-python <3.15`.

## 0.1.0 — 2026-10-30

- Primera versión: CLI `todo-a-markdown` y skill.
- EPUB con capítulos desde el TOC (NCX o `nav.xhtml`), imágenes a `<nombre>_adjuntos/` y notas al pie sin wikilinks falsos.
- PDF con pymupdf4llm (tablas, sin encabezados ni pies de página), OCR opcional con RapidOCR (`[ocr]`) y Docling opcional (`[docling]`, `--motor docling`) para papers a dos columnas.
- Repara acentos sueltos de PDF hechos con LaTeX o Docling («Famı´lia», «Sau´ ´ de» → «Família», «Saúde»), URL partidas, guiones entre números («158-173») y compuestos («bias-correction») que el motor quitó al unir líneas.
- Título y autor del PDF solo si aparecen en el texto; títulos sin duplicar y un único H1.
- Mejorado en 5 rondas de revisión contra `ejemplos/checklist.md` (Gemini Flash revisa, Claude verifica y corrige).
- DOCX, PPTX, XLSX, HTML y CSV con MarkItDown, imágenes incluidas; MOBI, AZW3 y FB2 vía Calibre.
- Informe de calidad JSON por archivo: estado `ok`/`revisar`/`error`, motivos, avisos y métricas.
- Nunca reemplaza un `.md` existente sin `--sobrescribir`.
