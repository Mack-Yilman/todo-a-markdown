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
        sin_texto, palabras, derecha, cuerpo = 0, 0, 0, 0
        for pagina in doc:
            texto = pagina.get_text()
            palabras += contar_palabras(texto)
            if len(texto.strip()) < 20:
                sin_texto += 1
            for b in pagina.get_text("blocks"):
                if b[6] == 0 and len(b[4].strip()) > 150:  # bloques de texto corrido, no títulos ni pies
                    cuerpo += 1
                    derecha += b[0] > pagina.rect.width * 0.45
        meta = doc.metadata or {}
        return {
            "paginas": doc.page_count,
            "paginas_sin_texto": sin_texto,
            "palabras": palabras,
            # Calibrado: papers a dos columnas ~0,4 de bloques que empiezan pasada la mitad; una columna, 0.
            "dos_columnas": cuerpo > 0 and derecha / cuerpo >= 0.2,
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


# Un enlace partido por el salto de línea del PDF: «https://hdl.handle.net/20. 500.12196/…», «https://doi.org/ 10.1371/…».
# Solo se une si lo que sigue también parece URL (tiene / o un punto interno): «https://x.org/ and» queda igual.
URL_PARTIDA = re.compile(r"(https?://\S*[/.\-]) (?=[\w%]\S*?[/.]\w)")
NEGRITA_CON_ESPACIO = re.compile(r"\*\*(\S[^*\n]*?)\s+\*\*")


def _limpiar(md):
    md = COMENTARIO.sub("", md)  # marcas «Start/End of picture text» del modo layout
    md = NEGRITA_CON_ESPACIO.sub(r"**\1** ", md)
    return unir_acentos(URL_PARTIDA.sub(r"\1", md))


def instalar_extra(extra):
    return f'uv tool install --force "todo-a-markdown[{extra}] @ git+https://github.com/Mack-Yilman/todo-a-markdown"'


def convertir_pymupdf(ruta, carpeta_adj, carpeta_rel, ocr):
    import pymupdf4llm

    if ocr:
        from pymupdf4llm.helpers.document_layout import select_ocr_function
        if select_ocr_function() is None:
            raise RuntimeError(f"no hay motor de OCR instalado. Reinstala con OCR: {instalar_extra('ocr')}")
    opciones = dict(header=False, footer=False, show_progress=False, use_ocr=ocr, force_ocr=False)
    if carpeta_adj:
        os.makedirs(carpeta_adj, exist_ok=True)
        opciones.update(write_images=True, image_path=carpeta_adj, image_format="png")
    md = _limpiar(pymupdf4llm.to_markdown(ruta, **opciones))
    return _relativizar(md, carpeta_adj, carpeta_rel) if carpeta_adj else md


def convertir_docling(ruta, carpeta_adj, carpeta_rel, ocr):
    """Más fiel en papers a dos columnas y tablas; ~10 s por página en CPU y ~1,5 GB de RAM."""
    try:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ImageRefMode, PictureItem
    except ImportError as e:
        raise RuntimeError(f"Docling no está instalado (ocupa ~1,6 GB). Instálalo con: {instalar_extra('docling')}") from e

    opciones = PdfPipelineOptions(do_ocr=ocr, generate_picture_images=bool(carpeta_adj))
    # El lector por defecto (docling-parse) cerró el proceso sin error con un PDF de PLOS; pypdfium no.
    formato = PdfFormatOption(pipeline_options=opciones, backend=PyPdfiumDocumentBackend)
    doc = DocumentConverter(format_options={InputFormat.PDF: formato}).convert(ruta).document
    marca = "<!-- imagen -->"
    md = doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER, image_placeholder=marca if carpeta_adj else "")
    if carpeta_adj:
        os.makedirs(carpeta_adj, exist_ok=True)
        partes, salida = md.split(marca), []
        figuras = [it for it, _ in doc.iterate_items() if isinstance(it, PictureItem)]
        for i, parte in enumerate(partes[:-1]):
            salida.append(parte)
            imagen = figuras[i].get_image(doc) if i < len(figuras) else None
            if imagen is not None and min(imagen.size) >= MIN_LADO_PX:
                nombre = f"figura-{i + 1:03d}.png"
                imagen.save(os.path.join(carpeta_adj, nombre))
                salida.append(enlace_imagen(carpeta_rel, nombre))
        md = "".join(salida + partes[-1:])
    return _limpiar(md)


def convertir(ruta, carpeta_adj, carpeta_rel, ocr=False, motor="pymupdf"):
    if motor == "docling":
        if ocr:  # shortcut: el OCR de Docling necesita EasyOCR o su propio RapidOCR; no se probó en este equipo
            raise RuntimeError("--ocr no está disponible con --motor docling; usa el motor por defecto para PDF escaneados")
        return convertir_docling(ruta, carpeta_adj, carpeta_rel, ocr)
    return convertir_pymupdf(ruta, carpeta_adj, carpeta_rel, ocr)


