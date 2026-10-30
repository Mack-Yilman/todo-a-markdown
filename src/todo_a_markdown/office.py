"""DOCX, PPTX, XLSX, HTML y CSV → Markdown con MarkItDown; MOBI/AZW3/FB2 → EPUB con Calibre."""

import os
import re
import shutil
import subprocess
import zipfile

from .comun import extraer_data_uris, quitar_data_uris, verificar_zip

# Calibre no agrega ebook-convert al PATH en macOS, y en Windows solo al abrir una sesión nueva.
CALIBRE_RUTAS = (r"C:\Program Files\Calibre2\ebook-convert.exe", "/Applications/calibre.app/Contents/MacOS/ebook-convert")


def convertir(ruta, carpeta_adj, carpeta_rel, prefijo):
    from markitdown import MarkItDown

    if ruta.lower().endswith((".docx", ".pptx", ".xlsx")):
        with zipfile.ZipFile(ruta) as z:
            verificar_zip(z)
    res = MarkItDown().convert(ruta, keep_data_uris=True)
    md = re.sub(r"[ \t]*<!--.*?-->[ \t]*\n?", "", res.markdown, flags=re.S)  # «<!-- Slide number: 1 -->»
    # Una tabla de Word sin fila de encabezado sale con un encabezado vacío: la primera fila real pasa a serlo.
    md = re.sub(r"(?m)^\|(?:[ \t]*\|)+\n(\|(?:[ \t]*:?-+:?[ \t]*\|)+)\n(\|.*\|)$", r"\2\n\1", md)
    if ruta.lower().endswith(".pptx"):
        md = re.sub(r"(?m)^# ", "## ", md)  # cada diapositiva es una sección; el único H1 es el título del archivo
    md = extraer_data_uris(md, carpeta_adj, carpeta_rel, prefijo) if carpeta_adj else quitar_data_uris(md)
    return md, (res.title or "").strip()


def calibre_a_epub(ruta, carpeta_tmp):
    """Devuelve la ruta de un EPUB temporal convertido con `ebook-convert` de Calibre."""
    exe = shutil.which("ebook-convert") or next((r for r in CALIBRE_RUTAS if os.path.exists(r)), None)
    if not exe:
        raise RuntimeError("este formato necesita Calibre (ebook-convert); instálalo desde https://calibre-ebook.com")
    destino = os.path.join(carpeta_tmp, "libro.epub")
    proc = subprocess.run([exe, ruta, destino], stdin=subprocess.DEVNULL, capture_output=True, timeout=900)
    if proc.returncode != 0 or not os.path.exists(destino):
        error = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["sin detalle"]
        raise RuntimeError(f"Calibre no pudo convertir el archivo: {error[0]}")
    return destino
