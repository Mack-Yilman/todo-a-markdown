"""PDF → Markdown con pymupdf4llm (modo layout: columnas, tablas y títulos; OCR con RapidOCR si está instalado)."""

import os
import re
import unicodedata
import urllib.parse

import pymupdf

from .comun import contar_palabras, enlace_imagen

IMAGEN_MD = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
COMENTARIO = re.compile(r"[ \t]*<!--.*?-->[ \t]*\n?", re.S)
MIN_LADO_PX = 40  # a 150 ppp, ~7 mm: menos que eso es decoración, no una figura

# Los PDF hechos con LaTeX guardan los acentos como caracteres sueltos: «Famı´lia», «Gonc¸alo», «CadU<sup>´</sup> nico».
# Acento suelto → (diacrítico combinable, letras que lo admiten). Solo esas parejas: «don´t» queda igual.
VOCALES = "aeiouyAEIOUYı"
ACENTOS = {
    "´": ("́", VOCALES + "cCsSzZ"), "`": ("̀", VOCALES), "¨": ("̈", VOCALES),
    "ˆ": ("̂", VOCALES), "˜": ("̃", "aAnNoO"), "¸": ("̧", "cCsStT"),
    "ˇ": ("̌", "cCsSzZrReEnN"), "˚": ("̊", "aAuU"),
}
# El lookahead negativo deja quietos los ´ usados como apóstrofo («who´s», «I´m», «we´ve»).
ACENTO_SUELTO = re.compile(r"(\w)(?:<sup>)?([´`¨ˆ˜¸ˇ˚])(?:</sup>)?(?!(?:s|t|m|d|re|ll|ve)\b)(?: (?=[a-zà-ÿ]))?")


def unir_acentos(md):
    def unir(m):
        letra, acento = m.group(1), m.group(2)
        combinable, letras = ACENTOS[acento]
        if letra not in letras:
            return m.group(0)
        return unicodedata.normalize("NFC", ("i" if letra == "ı" else letra) + combinable)
    return ACENTO_SUELTO.sub(unir, md)


def analizar(ruta):
    """Datos del original para el informe: páginas, páginas sin texto, palabras y metadatos."""
    with pymupdf.open(ruta) as doc:
        if doc.needs_pass:
            raise ValueError("el PDF está protegido con contraseña")
        sin_texto, palabras = 0, 0
        for pagina in doc:
            texto = pagina.get_text()
            palabras += contar_palabras(texto)
            if len(texto.strip()) < 20:
                sin_texto += 1
        meta = doc.metadata or {}
        return {
            "paginas": doc.page_count,
            "paginas_sin_texto": sin_texto,
            "palabras": palabras,
            "title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
        }


def _relativizar(md, carpeta_adj, carpeta_rel):
    """pymupdf4llm escribe rutas absolutas; Obsidian necesita rutas relativas a la nota.
    De paso descarta las imágenes diminutas (viñetas, filetes, logos de 1 cm) que solo ensucian la nota."""
    def cambiar(m):
        nombre = os.path.basename(urllib.parse.unquote(m.group(2)).replace("\\", "/"))
        archivo = os.path.join(carpeta_adj, nombre)
        if not os.path.exists(archivo):
            return m.group(0)
        pix = pymupdf.Pixmap(archivo)
        if min(pix.width, pix.height) < MIN_LADO_PX:
            pix = None
            os.remove(archivo)
            return ""
        return enlace_imagen(carpeta_rel, nombre, m.group(1))
    return IMAGEN_MD.sub(cambiar, md)


def convertir(ruta, carpeta_adj, carpeta_rel, ocr):
    import pymupdf4llm

    if ocr:
        from pymupdf4llm.helpers.document_layout import select_ocr_function
        if select_ocr_function() is None:
            raise RuntimeError(
                "no hay motor de OCR instalado. Reinstala con OCR: "
                'uv tool install --force "todo-a-markdown[ocr] @ git+https://github.com/Mack-Yilman/todo-a-markdown"'
            )
    opciones = dict(header=False, footer=False, show_progress=False, use_ocr=ocr, force_ocr=False)
    if carpeta_adj:
        os.makedirs(carpeta_adj, exist_ok=True)
        opciones.update(write_images=True, image_path=carpeta_adj, image_format="png")
    md = pymupdf4llm.to_markdown(ruta, **opciones)
    md = unir_acentos(COMENTARIO.sub("", md))  # sin marcas «Start/End of picture text» del modo layout
    return _relativizar(md, carpeta_adj, carpeta_rel) if carpeta_adj else md


