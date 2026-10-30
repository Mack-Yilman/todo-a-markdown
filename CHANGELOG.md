# Changelog

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
