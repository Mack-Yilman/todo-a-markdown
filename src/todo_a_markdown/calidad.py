"""Informe de calidad de una conversión: estado `ok` o `revisar`, con motivos y avisos legibles."""

import os
import re
import urllib.parse
from collections import Counter

from .comun import WIKILINK_FALSO, contar_palabras

MOJIBAKE = re.compile(r"Ã[\x80-\xbf]|â€|Â[\xa0-\xbf]")
IMAGEN = re.compile(r"!\[[^\[\]]*\]\(([^)\[\n]+)\)")  # sin `[` para que `![![![…` no sea cuadrático
TITULO = re.compile(r"^(#{1,6}) \S", re.M)

# Umbrales (calibrados con el corpus de ejemplos/; ver CLAUDE.md antes de cambiarlos).
RATIO_MIN = {"pdf": 0.85, "epub": 0.9}  # el PDF pierde encabezados, pies y números de página a propósito
RATIO_MAX = 1.15
PALABRAS_DOC_LARGO = 3000
PALABRAS_POR_SECCION = 20000  # un libro de 100 000 palabras con un solo ## tampoco se puede navegar


def _cuerpo(md):
    return re.sub(r"\A---\n.*?\n---\n", "", md, flags=re.S)


def evaluar(md, ruta_md, formato, fuente):
    """`fuente`: datos del original (palabras, paginas, paginas_sin_texto), o {} si no se pueden medir."""
    cuerpo = _cuerpo(md)
    motivos, avisos = [], []
    m = {"palabras": contar_palabras(IMAGEN.sub("", cuerpo)), "lineas": md.count("\n")}

    niveles = [len(h) for h in TITULO.findall(cuerpo)]
    m["titulos"] = {f"h{n}": niveles.count(n) for n in range(1, 4) if niveles.count(n)}
    secciones = sum(n >= 2 for n in niveles)
    if m["palabras"] > PALABRAS_DOC_LARGO and secciones < max(1, m["palabras"] // PALABRAS_POR_SECCION):
        motivos.append(f"sin_titulos: documento largo con pocos títulos ## o ### ({secciones}); la navegación en Obsidian será pobre")
    saltos = sum(1 for a, b in zip(niveles, niveles[1:]) if b > a + 1)
    if saltos:
        avisos.append(f"saltos_de_nivel: {saltos} títulos saltan un nivel (p. ej., # → ###)")

    con_ocr = fuente.get("ocr") and fuente.get("paginas_sin_texto")
    if fuente.get("palabras") and not con_ocr:  # con OCR, el original no tiene texto con qué comparar
        ratio = m["palabras"] / fuente["palabras"]
        m["palabras_fuente"], m["ratio"] = fuente["palabras"], round(ratio, 3)
        minimo = RATIO_MIN.get(formato, 0.9)
        if ratio < minimo:
            motivos.append(f"texto_perdido: el Markdown tiene {ratio:.0%} de las palabras del original (mínimo {minimo:.0%})")
        elif ratio > RATIO_MAX:
            avisos.append(f"texto_duplicado: el Markdown tiene {ratio:.0%} de las palabras del original")

    m["mojibake"] = len(MOJIBAKE.findall(cuerpo))
    if m["mojibake"] >= 3:
        motivos.append(f"mojibake: {m['mojibake']} caracteres mal decodificados (Ã, â€)")
    elif m["mojibake"]:
        avisos.append(f"mojibake: {m['mojibake']} caracteres sospechosos (Ã, â€)")

    # � casi siempre viene del original: símbolos (≤, ≥, ±, letras griegas) sin Unicode en la fuente del PDF.
    ilegibles = list(re.finditer("�", cuerpo))
    m["ilegibles"] = len(ilegibles)
    if ilegibles:
        i = ilegibles[0].start()
        ejemplo = " ".join(cuerpo[max(0, i - 40): i + 15].split())
        avisos.append(f"simbolos_ilegibles: {len(ilegibles)} caracteres � (símbolos como ≤, ≥ o ± sin Unicode en el original); p. ej., «{ejemplo}»")

    formulas = cuerpo.count("*[fórmula no convertida")
    if formulas:
        motivos.append(f"formulas_omitidas: {formulas} ecuaciones no se pudieron convertir; quedaron marcadas como «[fórmula no convertida]»")

    m["wikilinks_falsos"] = len(WIKILINK_FALSO.findall(cuerpo))
    if m["wikilinks_falsos"]:
        motivos.append(f"wikilinks_falsos: {m['wikilinks_falsos']} notas [[n]] que Obsidian tomará por enlaces")

    base = os.path.dirname(ruta_md)
    imagenes = [urllib.parse.unquote(u) for u in IMAGEN.findall(cuerpo) if not u.startswith(("http:", "https:", "data:"))]
    # Una ruta absoluta nunca es nuestra, y consultar \\servidor\x en Windows le enviaría a ese servidor el hash NTLM del usuario.
    rotas = [u for u in imagenes if u.startswith(("\\", "/")) or os.path.isabs(u) or not os.path.exists(os.path.join(base, u))]
    m["imagenes"], m["imagenes_rotas"] = len(imagenes), len(rotas)
    if rotas:
        motivos.append(f"imagenes_rotas: {len(rotas)} imágenes enlazadas no existen (p. ej., {rotas[0]})")

    if "paginas" in fuente:
        paginas, vacias = fuente["paginas"], fuente.get("paginas_sin_texto", 0)
        m["paginas"], m["paginas_sin_texto"] = paginas, vacias
        if con_ocr:  # el OCR no se puede medir contra el original: siempre pide una revisión humana
            motivos.append(f"ocr: {vacias} de {paginas} páginas se leyeron con OCR; pueden tener errores en cifras, dosis, nombres y tablas, y columnas mezcladas: verifícalas contra el original")
        elif vacias and vacias >= paginas / 2:
            motivos.append(f"escaneado: {vacias} de {paginas} páginas no tienen texto; hace falta OCR (--ocr)")
        elif vacias:
            lista = ", ".join(map(str, fuente.get("lista_sin_texto", [])[:10]))
            avisos.append(f"paginas_sin_texto: {vacias} de {paginas} páginas sin texto (escaneadas o solo imagen): {lista}")
        columnas = fuente.get("paginas_columnas")
        donde = "varias páginas" if columnas == ["varias"] else "las páginas " + ", ".join(map(str, (columnas or [])[:10]))
        if columnas and fuente.get("motor") == "docling":
            motivos.append(f"columnas: Docling ordena mejor las columnas, pero a veces intercala barras laterales y recuadros; revisa el orden de lectura en {donde}")
        elif columnas:
            motivos.append(f"dos_columnas: hay columnas o una barra lateral en {donde}, y el motor pymupdf a veces "
                           "las intercala; reconvierte con --motor docling o revisa el orden de lectura ahí")
        if paginas >= 4:
            lineas = Counter(ln.strip() for ln in cuerpo.splitlines() if 3 < len(ln.strip()) < 80 and not ln.startswith(("#", "|", "!", "<!--", "*[fórmula")))
            repetidas = [ln for ln, n in lineas.items() if n >= max(3, paginas / 2)]
            if repetidas:
                avisos.append(f"lineas_repetidas: {len(repetidas)} líneas se repiten en muchas páginas (¿encabezados o pies?), p. ej., «{repetidas[0][:50]}»")

    return {"estado": "revisar" if motivos else "ok", "motivos": motivos, "avisos": avisos, "metricas": m}
