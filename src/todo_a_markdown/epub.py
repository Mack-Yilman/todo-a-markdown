"""EPUB → Markdown. Basado en base/conversor_epub.py, probado con 30 libros maquetados en InDesign."""

import os
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

import lxml.html

from .comun import contar_palabras, enlace_imagen, nombre_seguro, sanitizar

IGNORAR_EN_TOC = ["portada", "créditos", "copyright", "índice", "dedicatoria", "cover", "contents"]
BLOQUES = {"div", "section", "article", "aside", "header", "footer", "nav", "figure", "figcaption", "main", "body", "dl", "dd", "dt", "pre"}
IMAGENES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def _envolver(inner, marca):
    """`**texto**` con los espacios de los bordes fuera de las marcas (si no, Markdown no lo reconoce)."""
    limpio = inner.strip()
    if not limpio:
        return inner
    izq = inner[: len(inner) - len(inner.lstrip())]
    der = inner[len(inner.rstrip()):]
    return f"{izq}{marca}{limpio}{marca}{der}"


class ConversorEpub:
    def __init__(self, ruta, carpeta_adj=None, carpeta_rel=None):
        self.ruta = ruta
        self.carpeta_adj = carpeta_adj  # None = sin imágenes
        self.carpeta_rel = carpeta_rel
        self.toc = {}
        self.inyectados = set()
        self.imagenes = {}
        self.avisos = []
        self.palabras_fuente = 0
        self.meta = {}

    def _leer_toc(self, z, opf_dir, manifest_nav):
        ncx = next((n for n in z.namelist() if n.lower().endswith(".ncx")), None)
        if ncx:
            base = posixpath.dirname(ncx)
            raiz = ET.fromstring(z.read(ncx))
            for np in raiz.findall(".//{*}navPoint"):
                texto = np.find(".//{*}text")
                content = np.find(".//{*}content")
                if texto is not None and content is not None and texto.text:
                    self._agregar_toc(base, " ".join(texto.text.split()), content.attrib.get("src", ""))
        elif manifest_nav:
            # EPUB3 sin NCX: el TOC está en el documento de navegación (nav.xhtml).
            base = posixpath.dirname(manifest_nav)
            arbol = lxml.html.fromstring(self._decodificar(z.read(manifest_nav)))
            for a in arbol.xpath("//nav//a[@href]"):
                self._agregar_toc(base, " ".join(a.text_content().split()), a.get("href"))

    def _agregar_toc(self, base, titulo, src):
        titulo = sanitizar(titulo)
        if not titulo or not src or any(i in titulo.lower() for i in IGNORAR_EN_TOC):
            return
        completo = posixpath.normpath(posixpath.join(base, urllib.parse.unquote(src)))
        archivo, _, ancla = completo.partition("#")
        self.toc.setdefault((archivo, ancla), titulo)

    def _extraer_imagenes(self, z):
        if not self.carpeta_adj:
            return
        os.makedirs(self.carpeta_adj, exist_ok=True)
        usados = set()
        for n in z.namelist():
            if n.lower().endswith(IMAGENES):
                nombre = nombre_seguro(os.path.basename(n))
                base, ext = os.path.splitext(nombre)
                i = 1
                while nombre in usados:  # dos imágenes con el mismo nombre en carpetas distintas
                    nombre = f"{base}_{i}{ext}"
                    i += 1
                usados.add(nombre)
                with open(os.path.join(self.carpeta_adj, nombre), "wb") as f:
                    f.write(z.read(n))
                self.imagenes[n] = nombre

    @staticmethod
    def _decodificar(datos):
        # InDesign no declara charset: decodificar a mano evita el mojibake; lxml rechaza el prólogo XML en str.
        texto = datos.decode("utf-8", errors="replace")
        return re.sub(r"^\s*<\?xml[^>]*\?>", "", texto)

    def _nodo(self, el, archivo):
        if not isinstance(el.tag, str):
            return sanitizar(el.tail or "")
        tag = el.tag.lower().split("}")[-1]
        cola = sanitizar(el.tail or "")
        if tag in ("script", "style", "head", "meta", "link", "title"):
            return cola

        cabecera = ""
        el_id = el.get("id") or el.get("name")
        clave = (archivo, el_id)
        if el_id and clave in self.toc and clave not in self.inyectados:
            cabecera = f"\n\n## {self.toc[clave]}\n\n"
            self.inyectados.add(clave)

        if tag == "img" or tag == "image":
            src = el.get("src") or el.get("{http://www.w3.org/1999/xlink}href") or ""
            if not self.carpeta_adj or not src:
                return cabecera + cola
            ruta = posixpath.normpath(posixpath.join(posixpath.dirname(archivo), urllib.parse.unquote(src)))
            nombre = self.imagenes.get(ruta)
            if not nombre:
                self.avisos.append(f"imagen no encontrada en el EPUB: {src}")
                return cabecera + cola
            return f"{cabecera}\n\n{enlace_imagen(self.carpeta_rel, nombre, el.get('alt', ''))}\n\n{cola}"

        if tag == "table":
            return cabecera + self._tabla(el) + cola
        if tag == "br":
            return "\n" + cola

        inner = sanitizar(el.text or "") + "".join(self._nodo(c, archivo) for c in el)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            limpio = " ".join(inner.split())
            nivel = "##" if int(tag[1]) <= 2 else "###"
            if limpio and cabecera and limpio.lower() in cabecera.lower():
                cabecera = ""  # el TOC y el título del capítulo dicen lo mismo: no duplicar
            return cabecera + (f"\n\n{nivel} {limpio}\n\n" if limpio else "") + cola
        if tag == "p":
            limpio = " ".join(inner.split())
            return cabecera + (f"\n\n{limpio}\n\n" if limpio else "") + cola
        if tag in ("strong", "b"):
            return _envolver(inner, "**") + cola
        if tag in ("em", "i"):
            return _envolver(inner, "*") + cola
        if tag == "blockquote":
            lineas = [ln.strip() for ln in inner.split("\n") if ln.strip()]
            return cabecera + "\n\n" + "\n".join(f"> {ln}" for ln in lineas) + "\n\n" + cola
        if tag == "li":
            padre = el.getparent()
            marca = "-"
            if padre is not None and padre.tag == "ol":
                marca = f"{[c for c in padre if c.tag == 'li'].index(el) + 1}."
            return cabecera + f"{marca} {' '.join(inner.split())}\n" + cola
        if tag in ("ul", "ol"):
            return cabecera + f"\n\n{inner}\n\n" + cola
        if tag in BLOQUES:
            return cabecera + f"\n\n{inner}\n\n" + cola
        return cabecera + inner + cola

    @staticmethod
    def _tabla(el):
        filas = []
        for tr in el.xpath(".//tr"):
            celdas = [" ".join("".join(td.itertext()).split()).replace("|", "/") for td in tr.xpath("./td | ./th")]
            if celdas:
                filas.append(celdas)
        if not filas:
            return ""
        n = max(len(f) for f in filas)
        filas = [f + [""] * (n - len(f)) for f in filas]
        md = [f"| {' | '.join(filas[0])} |", f"| {' | '.join(['---'] * n)} |"]
        md += [f"| {' | '.join(f)} |" for f in filas[1:]]
        return "\n\n" + "\n".join(md) + "\n\n"

    def convertir(self):
        with zipfile.ZipFile(self.ruta) as z:
            opf = None
            try:
                contenedor = ET.fromstring(z.read("META-INF/container.xml"))
                rf = contenedor.find(".//{*}rootfile")
                opf = rf.get("full-path") if rf is not None else None
            except (KeyError, ET.ParseError):
                pass
            opf = opf or next((n for n in z.namelist() if n.lower().endswith(".opf")), None)
            if not opf:
                raise ValueError("el EPUB no tiene archivo OPF (¿está dañado o no es un EPUB?)")

            opf_dir = posixpath.dirname(opf)
            raiz = ET.fromstring(z.read(opf))
            self.meta = {
                "title": " ".join((raiz.findtext(".//{*}metadata/{*}title") or "").split()),
                "author": " ".join((raiz.findtext(".//{*}metadata/{*}creator") or "").split()),
            }
            manifest, nav = {}, None
            for item in raiz.findall(".//{*}manifest/{*}item"):
                ruta = posixpath.normpath(posixpath.join(opf_dir, urllib.parse.unquote(item.get("href", ""))))
                manifest[item.get("id")] = ruta
                if "nav" in (item.get("properties") or "").split():
                    nav = ruta

            self._leer_toc(z, opf_dir, nav)
            self._extraer_imagenes(z)

            spine = []
            for ref in raiz.findall(".//{*}spine/{*}itemref"):
                ruta = manifest.get(ref.get("idref"))
                if ruta and ruta not in spine and ruta.lower().endswith((".xhtml", ".html", ".htm", ".xml")):
                    spine.append(ruta)

            secciones = []
            for archivo in spine:
                try:
                    arbol = lxml.html.fromstring(self._decodificar(z.read(archivo)))
                except (KeyError, ValueError, lxml.etree.ParserError) as e:
                    self.avisos.append(f"no se pudo leer {archivo}: {e}")
                    continue
                cuerpo = arbol.find(".//body")
                cuerpo = arbol if cuerpo is None else cuerpo
                self.palabras_fuente += contar_palabras(" ".join(cuerpo.itertext()))
                secciones.append(self._nodo(cuerpo, archivo))

        return sanitizar("\n\n".join(secciones))
