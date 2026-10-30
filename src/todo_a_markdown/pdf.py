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
# Docling además los separa con espacios y a veces ya puso la tilde: «Famí ´ lia», «U ´ nico», «Gonç ¸ alo».
ACENTO_SUELTO = re.compile(r"(\w)(?:<sup>)? ?([´`¨ˆ˜¸ˇ˚])(?:</sup>)?(?!(?:s|t|m|d|re|ll|ve)\b)(?: (?=[a-zà-ÿ]))?")


def unir_acentos(md):
    def unir(m):
        letra, acento = m.group(1), m.group(2)
        combinable, letras = ACENTOS[acento]
        base = unicodedata.normalize("NFD", letra)
        if combinable in base[1:]:  # la letra ya trae ese acento: sobra el suelto
            return letra
        if base[0] not in letras or len(base) > 1:
            return m.group(0)
        return unicodedata.normalize("NFC", ("i" if letra == "ı" else letra) + combinable)
    # Docling a veces repite el acento («Sau´ ´ de»): la 1.ª pasada deja «Saú ´ de» y la 2.ª quita el sobrante.
    for _ in range(3):
        nuevo = ACENTO_SUELTO.sub(unir, md)
        if nuevo == md:
            break
        md = nuevo
    return md


def analizar(ruta):
    """Datos del original para el informe: páginas, páginas sin texto, palabras y metadatos."""
    with pymupdf.open(ruta) as doc:
        if doc.needs_pass:
            raise ValueError("el PDF está protegido con contraseña")
        sin_texto, palabras, derecha, cuerpo, con_columnas, todo = [], 0, 0, 0, [], []
        for n, pagina in enumerate(doc, 1):
            texto = pagina.get_text()
            todo.append(texto)
            palabras += contar_palabras(texto)
            if len(texto.strip()) < 20:
                sin_texto.append(n)
            ancho = pagina.rect.width
            # x de los bloques de texto corrido (no títulos ni pies)
            xs = [b[0] for b in pagina.get_text("blocks") if b[6] == 0 and len(b[4].strip()) > 150]
            cuerpo += len(xs)
            derecha += sum(x > ancho * 0.45 for x in xs)
            if len(xs) >= 4:  # columnas o barra lateral en esta página: bloques que arrancan en dos x separadas
                izq, der = min(xs), max(xs)
                if (der - izq >= 0.25 * ancho and sum(x < izq + 0.05 * ancho for x in xs) >= 2
                        and sum(x > der - 0.05 * ancho for x in xs) >= 2):
                    con_columnas.append(n)
        meta = doc.metadata or {}
        # Calibrado con el corpus: en un paper a dos columnas ~40 % de los bloques empiezan pasada la mitad (una
        # columna: 0 %); la barra lateral de PLOS solo se ve página por página (págs. 1–2).
        if cuerpo and derecha / cuerpo >= 0.2 and not con_columnas:
            con_columnas = ["varias"]
        return {
            "paginas": doc.page_count,
            "paginas_sin_texto": len(sin_texto),
            "lista_sin_texto": sin_texto,
            "palabras": palabras,
            "paginas_columnas": con_columnas,
            "guiones": guiones_de_fin_de_linea("\n".join(todo)),
            "title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
        }


def _clave(texto):
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFC", texto)).lower()


def metadatos_confiables(fuente, md):
    """Los metadatos de un PDF a veces son de quien lo armó («REVISTA MEDICA HEREDIANA VOL», el nombre del
    diagramador): solo se usan si el título, o el primer autor, aparecen al inicio del texto convertido."""
    inicio = _clave(md[:8000])
    datos = {}
    if fuente.get("title") and _clave(fuente["title"]) in inicio:
        datos["title"] = fuente["title"]
    primer_autor = re.split(r"[,;]| and | y ", fuente.get("author") or "")[0]
    if primer_autor.strip() and _clave(primer_autor) in inicio:
        datos["author"] = fuente["author"]
    return datos


def guiones_de_fin_de_linea(texto):
    """Los motores quitan todo guion de fin de línea como si cortara una sílaba. Devuelve [(unido, correcto)] para
    los que no lo eran, con el original como única evidencia:
    - entre números: «158-⏎173» (páginas de una referencia) no es «158173»;
    - guion suspendido: «image-⏎and transform» es «image- and»;
    - compuesto: «bias-⏎correction» solo si el original escribe «bias-correction» dentro de una línea.
    Un corte de sílaba («trata-⏎miento») no cumple ninguna y queda unido."""
    pares = set()
    for a, b in re.findall(r"(?<![\w-])(\d+)-[ \t]*\n\s*(\d+)(?!\d)", texto):
        pares.add((a + b, f"{a}-{b}"))
    for a, b in re.findall(r"(?<![\w-])([^\W\d_]{2,})-[ \t]*\n\s*([^\W\d_]{2,})(?![\w-])", texto):
        if b in ("and", "or", "y", "o", "e", "u"):
            pares.add((a + b, f"{a}- {b}"))
        elif f"{a}-{b}" in texto:
            pares.add((a + b, f"{a}-{b}"))
    return sorted(pares)


def restaurar_guiones(md, pares):
    for unido, correcto in pares:
        md = re.sub(rf"(?<![\w-]){re.escape(unido)}(?![\w-])", correcto, md)
    return md


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


FORMULA_OMITIDA = "*[fórmula no convertida: consúltala en el original]*"


def _quitar_texto_vertical(md):
    """Texto girado 90° (el sello lateral de arXiv, márgenes de revistas) sale como una letra por línea:
    6 o más líneas seguidas de hasta 3 caracteres se descartan."""
    lineas, salida, racha = md.split("\n"), [], []
    for ln in lineas + [None]:
        if ln is not None and (not ln.strip() or len(ln.strip()) <= 3) and (racha or ln.strip()):
            racha.append(ln)
            continue
        if sum(1 for r in racha if r.strip()) < 6:
            salida += racha
        racha = []
        if ln is not None:
            salida.append(ln)
    return "\n".join(salida)


def _limpiar(md):
    md = _quitar_texto_vertical(md)
    md = md.replace("<!-- formula-not-decoded -->", FORMULA_OMITIDA)  # Docling: que no desaparezca en silencio
    md = COMENTARIO.sub("", md)  # marcas «Start/End of picture text» del modo layout
    md = NEGRITA_CON_ESPACIO.sub(r"**\1** ", md)
    return unir_acentos(URL_PARTIDA.sub(r"\1", md))


def instalar_extra(extra):
    return f'uv tool install --python 3.13 --force "todo-a-markdown[{extra}] @ git+https://github.com/Mack-Yilman/todo-a-markdown"'


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


