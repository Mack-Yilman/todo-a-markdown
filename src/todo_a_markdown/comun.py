"""Utilidades compartidas: sanitización para Obsidian, frontmatter, enlaces e imágenes."""

import base64
import json
import os
import re
import urllib.parse
from datetime import date

# Dominios que el antivirus (Avast/Defender) detectó en bibliografías y por los que vació el .md
# en silencio. shortcut: lista fija; amplíala cuando aparezca otro caso.
DOMINIOS_NEUTRALIZAR = ["josephsoninstitute.org"]

WIKILINK_FALSO = re.compile(r"\^?\[\[(\d+)\]\]")


def sanitizar(texto):
    """Notas al pie `[[1]]` o `^[[1]]` → `(1)` (Obsidian las tomaría por wikilinks) y dominios neutralizados."""
    if not texto:
        return ""
    texto = WIKILINK_FALSO.sub(r"(\1)", texto)
    for dominio in DOMINIOS_NEUTRALIZAR:
        texto = texto.replace(dominio, dominio.replace(".", "[.]"))
    return texto


def contar_palabras(texto):
    """Cuenta los tokens con al menos una letra o número (ignora `#`, `|`, `---`, `-`)."""
    return sum(1 for t in texto.split() if any(c.isalnum() for c in t))


def frontmatter(meta):
    """YAML con los valores como cadenas JSON (son cadenas YAML válidas entre comillas dobles)."""
    lineas = ["---"]
    for clave, valor in meta.items():
        if valor:
            lineas.append(f"{clave}: {json.dumps(str(valor), ensure_ascii=False)}")
    lineas.append("---")
    return "\n".join(lineas) + "\n\n"


def hoy():
    # Fecha local (en Perú, la de UTC ya es mañana después de las 19:00).
    d = date.today()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def nombre_seguro(nombre):
    return re.sub(r"[^\w\-.]", "_", nombre)


def enlace_imagen(carpeta_rel, archivo, alt=""):
    """Enlace Markdown estándar y relativo; los espacios van como %20 (Obsidian y CommonMark lo aceptan)."""
    alt = alt.replace("[", "(").replace("]", ")").replace("\n", " ").strip()
    return f"![{alt}]({urllib.parse.quote(carpeta_rel + '/' + archivo)})"


DATA_URI = re.compile(r"!\[([^\]]*)\]\(data:image/([\w.+-]+);base64,([A-Za-z0-9+/=\s]+)\)")


def extraer_data_uris(md, carpeta_adj, carpeta_rel, prefijo):
    """Guarda las imágenes incrustadas en base64 (DOCX, PPTX, HTML) y deja enlaces relativos."""
    contador = [0]

    def guardar(m):
        alt, tipo, datos = m.group(1), m.group(2).lower(), m.group(3)
        try:
            contenido = base64.b64decode(re.sub(r"\s", "", datos), validate=True)
        except ValueError:
            return f"*[imagen ilegible: {alt}]*" if alt else ""
        contador[0] += 1
        ext = {"jpeg": "jpg", "svg+xml": "svg", "x-emf": "emf", "x-wmf": "wmf"}.get(tipo, tipo)
        archivo = f"{nombre_seguro(prefijo)}-{contador[0]:03d}.{ext}"
        os.makedirs(carpeta_adj, exist_ok=True)
        with open(os.path.join(carpeta_adj, archivo), "wb") as f:
            f.write(contenido)
        return enlace_imagen(carpeta_rel, archivo, alt)

    return DATA_URI.sub(guardar, md)


def quitar_data_uris(md):
    """Con --sin-imagenes: deja solo el texto alternativo, si lo hay."""
    return DATA_URI.sub(lambda m: f"*[imagen: {m.group(1)}]*" if m.group(1).strip() else "", md)


def limpiar_saltos(md):
    md = re.sub(r"[ \t]+\n", "\n", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
