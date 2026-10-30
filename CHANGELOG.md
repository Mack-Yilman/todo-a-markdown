# Changelog

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
