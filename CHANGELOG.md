# Changelog

## 0.1.0 — 2026-10-30

- Primera versión: CLI `todo-a-markdown` y skill.
- EPUB con capítulos desde el TOC (NCX o `nav.xhtml`), imágenes a `<nombre>_adjuntos/` y notas al pie sin wikilinks falsos.
- PDF con pymupdf4llm (columnas, tablas, sin encabezados ni pies de página) y OCR opcional con RapidOCR (`[ocr]`).
- DOCX, PPTX, XLSX, HTML y CSV con MarkItDown, imágenes incluidas; MOBI, AZW3 y FB2 vía Calibre.
- Informe de calidad JSON por archivo: estado `ok`/`revisar`/`error`, motivos, avisos y métricas.
- Nunca reemplaza un `.md` existente sin `--sobrescribir`.
