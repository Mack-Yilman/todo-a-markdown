"""EPUB → Markdown. Basado en base/conversor_epub.py, probado con 30 libros maquetados en InDesign."""

import os
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

import lxml.html

from .comun import contar_palabras, enlace_imagen, nombre_seguro, sanitizar, verificar_zip

BLOQUES = {"div", "section", "article", "aside", "header", "footer", "nav", "figure", "figcaption", "main", "body", "dl", "dd", "dt", "pre"}
IMAGENES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
SANGRIA = "\x03"
TITULO_INYECTADO = re.compile("\x01([^\x02]*)\x02")  # marca interna de un título del TOC hasta que el capítulo está armado


def _clave(texto):
    return re.sub(r"[\W_]", "", texto).lower()


def quitar_titulos_repetidos(md):
    """El título del TOC y el del cuerpo suelen decir lo mismo con otra caja o puntuación
    («## Primera parte. La elección…» y «## Primera parte La elección…», o «## Ocho objetivos» y «OCHO OBJETIVOS»):
    se conserva el primero y se quita el bloque siguiente si repite el texto."""
    bloques = md.split("\n\n")
    salida = []
    for b in bloques:
        previo = salida[-1] if salida else ""
        if previo.startswith("#") and b.strip():
            actual, titulo = _clave(b.lstrip("#")), _clave(previo.lstrip("#"))
            # «## Prólogo de James Clear» y luego «Prólogo»: el TOC ya dice más que el cuerpo.
            # Con punto final es una frase del libro («La casa.» bajo «## La casa de Bernarda Alba»).
            if actual == titulo or (actual and len(b) < 80 and titulo.startswith(actual) and not b.rstrip(" *_").endswith((".", ",", ";", ":", "!", "?", "»"))):
                continue
        salida.append(b)
    return "\n\n".join(salida)


def _sacar_titulos(inner):
    """Separa los títulos del TOC anidados en un elemento que se va a aplanar (`<p><a id="cap1"/>…</p>`): si no, quedarían
    en medio de la línea. shortcut: el título pasa antes del texto del elemento; solo importaría con un ancla a media frase."""
    titulos = TITULO_INYECTADO.findall(inner)
    return ("".join(f"\n\n{t}\n\n" for t in titulos), TITULO_INYECTADO.sub("", inner)) if titulos else ("", inner)


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
        if not titulo or not src:
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
        texto = datos.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"^\s*<\?xml[^>]*\?>", "", texto)

    def _con_titulo_del_toc(self, seccion, archivo):
        """Una entrada del TOC sin ancla apunta al archivo entero: el título va al inicio, salvo que ya esté ahí."""
        titulo = self.toc.get((archivo, ""))
        if not titulo or len(self.toc) < 2:
            return seccion
        bloques = [b.strip() for b in seccion.split("\n\n") if b.strip()]
        texto = [b for b in bloques if not b.startswith("![")]
        if not texto:  # portada u otra página de solo imagen
            return seccion
        clave, acumulado, repetidos = _clave(titulo), "", 0
        for b in texto[:4]:
            actual = _clave(b.lstrip("#"))
            if b.startswith("#") and actual and (actual in clave or clave in actual):
                return seccion
            acumulado += actual
            repetidos += 1
            if acumulado == clave:  # «Capítulo 1» + «El método» en párrafos: pasan a ser el título
                resto, quedan = [], repetidos
                for b2 in bloques:
                    if quedan and not b2.startswith("!["):
                        quedan -= 1
                        continue
                    resto.append(b2)
                return "\n\n".join([f"## {titulo}", *resto])
            if len(acumulado) > len(clave):
                break
        return f"## {titulo}\n\n{seccion}"

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
            cabecera = f"\n\n\x01## {self.toc[clave]}\x02\n\n"
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

        # Una lista dentro de un <li> va aparte: aplanada, un índice o todas las notas de un libro quedaban en una sola línea.
        sublistas = [c for c in el if isinstance(c.tag, str) and c.tag.lower().split("}")[-1] in ("ul", "ol")] if tag == "li" else []
        inner = sanitizar(el.text or "") + "".join(self._nodo(c, archivo) for c in el if c not in sublistas)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "b", "em", "i", "blockquote", "li"):
            anidados, inner = _sacar_titulos(inner)
            cabecera += anidados

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            limpio = " ".join(inner.split())
            nivel = "##" if int(tag[1]) <= 2 else "###"
            if limpio and cabecera and limpio.lower() in cabecera.lower():
                cabecera = ""  # el TOC y el título del capítulo dicen lo mismo: no duplicar
            return cabecera + (f"\n\n{nivel} {limpio}\n\n" if limpio else "") + cola
        if tag == "p":
            # «# #hashtag» o «- Autor» en un párrafo del libro no son un título ni una lista.
            limpio = re.sub(r"^(?=(?:#{1,6}|[-+]) )", r"\\", " ".join(inner.split()))
            return cabecera + (f"\n\n{limpio}\n\n" if limpio else "") + cola
        if tag in ("strong", "b"):
            return cabecera + _envolver(inner, "**") + cola
        if tag in ("em", "i"):
            return cabecera + _envolver(inner, "*") + cola
        if tag == "blockquote":
            lineas = [ln.strip() for ln in inner.split("\n") if ln.strip()]
            return cabecera + "\n\n" + "\n".join(f"> {ln}" for ln in lineas) + "\n\n" + cola
        if tag == "li":
            padre = el.getparent()
            marca = "-"
            if padre is not None and padre.tag == "ol":
                marca = f"{[c for c in padre if c.tag == 'li'].index(el) + 1}."
            anidada = "".join(self._nodo(c, archivo) for c in sublistas).splitlines()
            # \x03 es la sangría: el paso que quita la sangría del HTML borraría unos espacios.
            anidada = "".join(("" if ln.strip().startswith(("\x01", "#")) else SANGRIA) + ln.strip() + "\n" for ln in anidada if ln.strip())
            # El parser mete en un <li> sin cerrar lo que sigue (<h2>, más listas): solo el primer bloque es el ítem.
            bloques = [b for b in inner.split("\n\n") if b.strip()] or [""]
            resto = "".join(f"\n\n{b.strip()}\n\n" for b in bloques[1:])
            return cabecera + f"{marca} {' '.join(bloques[0].split())}\n" + anidada + resto + cola
        if tag in ("ul", "ol"):
            items = "\n".join(ln.strip() for ln in inner.splitlines() if ln.strip())  # sin la sangría ni los saltos del HTML
            items = re.sub(r"(?m)^(#{1,6} .*)$", r"\n\1\n", items)  # un título que venía dentro de un ítem conserva su línea en blanco
            return cabecera + f"\n\n{items}\n\n" + cola
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
            verificar_zip(z)
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
                seccion = TITULO_INYECTADO.sub(r"\1", self._nodo(cuerpo, archivo))
                secciones.append(self._con_titulo_del_toc(seccion, archivo))

        md = "\n\n".join(secciones)
        # La sangría del HTML no significa nada en un EPUB, pero en Markdown 4 espacios abren un bloque de código.
        md = re.sub(r"(?m)^[ \t]+", "", md).replace(SANGRIA, "   ")
        md = re.sub(r"\n{3,}", "\n\n", md)
        # Dos <i> seguidos separados por un espacio («*No* *hay devoluciones*»): un solo énfasis.
        md = re.sub(r"(?<=[^\s*])(\*{1,2}) \1(?=[^\s*])", " ", md)
        return sanitizar(quitar_titulos_repetidos(md))
