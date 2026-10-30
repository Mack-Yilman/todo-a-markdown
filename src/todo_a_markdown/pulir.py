"""Post-procesamiento de un .md: corrige estructura y empaquetado sin cambiar el texto del libro.

Dos pasos: `pulir <md>` aplica lo mecánico y devuelve propuestas agrupadas; `pulir <md> --aplicar <json>` aplica las que
el agente aceptó y empaqueta. Sin propuestas, el primer paso ya termina. La copia de seguridad es temporal y se borra al
terminar; una guardia compara las palabras de antes y de después, y si no cuadran restaura el original.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
from collections import Counter

from . import calidad
from .comun import limpiar_saltos

TITULO = re.compile(r"(#{1,6})[ \t]+(.*)")
VINETA = re.compile(r"[ \t]*(?:[-*+][ \t]+)?(?:[•▪●◦][ \t]*|·[ \t]+)")  # «•Ser objetivos» también: el libro no siempre deja espacio
SOLO_NUMERO = re.compile(r"(\d{1,3}|[IVXLC]{1,6})\.?")
WIKI_IMAGEN = re.compile(r"!\[\[[^\[\]\n]*\]\]")  # sin `[` para que `![[![[…` no sea cuadrático
NOTA_FINAL = re.compile(r"\[\^?\d{1,4}\]$")  # solo cifras: «[sic]» es texto del libro
CAPITULO = re.compile(r"(CAP[IÍ]TULO|PARTE|CHAPTER|PART|Cap[ií]tulo|Parte|Chapter|Part)[ \t]+([\w]{1,12})[.:]?(?:[ \t]+(.{1,90}))?")
PALABRA = re.compile(r"[^\W_]+")
FIN_DE_FRASE = (".", "!", "?", ":", ";", "»", "”", ")", '"', "…")
MIN_REPETIDAS, MIN_REPETIDAS_NUM = 15, 8  # un encabezado con número de página cambia y por capítulo se repite menos
MAX_GRUPOS = 12
MUESTRAS_SUBTITULOS = 30 # aceptar en bloque arrastra falsos: el agente ve más muestras y excluye líneas concretas
NO_ES_SUBTITULO = re.compile(r"ISBN|https?:|www\.|\.com\b|^\d+[.)] |^POR\b|^BY\b", re.I)
CONECTOR_FINAL = re.compile(r"\b(?:de|del|la|el|los|las|y|o|con|en|que|para|por|a|un|una|and|of|the|to|in)$", re.I)
MARCA_INDICE = "\x00"
EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg", ".emf", ".wmf")
PROHIBIDOS_NOMBRE =re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')


def _partir(md):
    """(frontmatter, cuerpo). Sin regex: `.*?` sobre un archivo entero no hace falta."""
    if md.startswith("---\n"):
        fin = md.find("\n---\n", 4)
        if fin != -1:
            return md[:fin + 5], md[fin + 5:]
    return "", md


def _unir(front, cuerpo):
    return f"{front}\n{cuerpo}" if front else cuerpo


def _palabras(texto):
    # Imágenes fuera: su ruta y su texto alternativo no son texto del libro.
    return PALABRA.findall(WIKI_IMAGEN.sub(" ", calidad.IMAGEN.sub(" ", texto)))


def verificar_fidelidad(antes, despues, quitado):
    """Devuelve el problema, o None. `despues` debe ser `antes` en el mismo orden, sin más que las palabras de `quitado`."""
    a, d = _palabras(antes), _palabras(despues)
    if Counter(a) - Counter(d) != Counter(_palabras(" ".join(quitado))) or Counter(d) - Counter(a):
        faltan = sum((Counter(a) - Counter(d)).values())
        sobran = sum((Counter(d) - Counter(a)).values())
        return f"guardia de fidelidad: {faltan} palabras faltan y {sobran} sobran respecto de lo autorizado"
    pos = iter(a)
    if not all(p in pos for p in d):  # `in` sobre un iterador avanza: comprueba que es subsecuencia, en tiempo lineal
        return "guardia de fidelidad: cambió el orden de las palabras"
    return None


def _codigo(lineas):
    marcas, dentro = [], False
    for ln in lineas:
        if ln.lstrip().startswith("```"):
            marcas.append(True)
            dentro = not dentro
        else:
            marcas.append(dentro)
    return marcas


def _sig_con_texto(lineas, i):
    for j in range(i + 1, len(lineas)):
        if lineas[j].strip():
            return j
    return None


def _celdas(fila):
    return re.sub(r"\\\|", "\x00", fila.strip()).strip("|").split("|")


def _arreglar_tabla(filas, cambios):
    if len(filas) < 2:
        return filas
    celdas = [_celdas(f) for f in filas]
    es_separador = lambda c: all(set(x.strip()) <= set("-:") and x.strip() for x in c)  # noqa: E731
    n = max(len(c) for c in celdas)
    salida = []
    for i, c in enumerate(celdas):
        if len(c) < n:
            cambios["tablas_columnas"] += 1
            c = c + (["---" if es_separador(c) else " "] * (n - len(c)))
        salida.append("| " + " | ".join(x.strip() for x in c).replace("\x00", "\\|") + " |" if len(c) != len(_celdas(filas[i])) else filas[i])
    if not es_separador(celdas[1]):
        cambios["tablas_sin_separador"] += 1
        salida.insert(1, "| " + " | ".join(["---"] * n) + " |")
    return salida


def corregir_estructura(cuerpo):
    """Lo mecánico, sin criterio. Devuelve (texto, cambios, palabras quitadas: notas y números repetidos en títulos)."""
    cambios, quitado = Counter(), []
    lineas = cuerpo.split("\n")
    codigo = _codigo(lineas)
    salida = []
    for ln, es_codigo in zip(lineas, codigo):
        if es_codigo:
            salida.append(ln)
            continue
        m = VINETA.match(ln)
        if m and ln[m.end():].strip():
            ln = "- " + ln[m.end():]
            cambios["vinetas"] += 1
        if ln.startswith("#") and not ln.strip("# \t"):
            cambios["titulos_vacios"] += 1
            continue
        m = TITULO.fullmatch(ln)
        if not m:
            salida.append(ln)
            continue
        marcas, texto = m.groups()
        imagenes =[x.group(0) for x in calidad.IMAGEN.finditer(texto)] + WIKI_IMAGEN.findall(texto)
        if imagenes:
            texto = WIKI_IMAGEN.sub("", calidad.IMAGEN.sub("", texto))
            cambios["imagenes_en_titulos"] += 1
        if "**" in texto or "__" in texto:
            texto = texto.replace("**", "").replace("__", "")
            cambios["negrita_en_titulos"] += 1
        texto = texto.strip()
        nota = NOTA_FINAL.search(texto)
        if nota and texto[:nota.start()].strip():
            quitado.append(nota.group(0))
            texto = texto[:nota.start()].rstrip()
            cambios["notas_en_titulos"] += 1
        if not texto.strip(" *_"):
            cambios["titulos_vacios"] += 1
            salida += imagenes
            continue
        salida.append(f"{marcas} {texto}")
        if imagenes:
            salida += ["", *imagenes, ""]

    # Títulos numéricos: «## 1» + «## El método» → «## 1. El método»; «### 1» tras «## 1. El método» sobra.
    lineas, codigo = salida, _codigo(salida)
    borrar, previo = set(), None
    for i, ln in enumerate(lineas):
        if codigo[i] or not ln.strip() or i in borrar:
            continue
        m = TITULO.fullmatch(ln)
        if not m:
            previo = None if not ln.startswith("![") else previo
            continue
        marcas, texto = m.groups()
        solo = SOLO_NUMERO.fullmatch(texto.strip())
        etiqueta = CAPITULO.fullmatch(texto.strip())  # «## Capítulo 6» + «EL CUERPO INTERIOR»
        if not solo and not (etiqueta and not etiqueta.group(3)):
            previo = texto
            continue
        numero = solo.group(1) if solo else texto.strip().rstrip(".:")
        if solo and previo and re.match(re.escape(numero) + r"\b", previo):
            borrar.add(i)
            quitado.append(numero)
            cambios["titulos_numericos"] += 1
            continue
        j = _sig_con_texto(lineas, i)
        if j is None or codigo[j]:
            continue
        sig = TITULO.fullmatch(lineas[j])
        texto_sig = sig.group(2).strip() if sig else lineas[j].strip().strip("*_").strip()
        # Un párrafo solo cuenta como título si es breve y no acaba como una frase; «Operación Crush:» sí vale.
        corto = len(texto_sig) <= 120 and not texto_sig.endswith((".", ",", ";")) and not lineas[j].startswith(("|", "!", "-", ">"))
        if not sig and not lineas[j].strip().startswith("**"):
            corto = corto and len(texto_sig) <= 70
        if corto and not SOLO_NUMERO.fullmatch(texto_sig):
            lineas[i] = f"{marcas} {numero}. {texto_sig.rstrip(':').rstrip()}"
            borrar.add(j)
            previo = lineas[i]
            cambios["titulos_numericos"] += 1
    lineas = [ln for i, ln in enumerate(lineas) if i not in borrar]

    # Tablas.
    codigo = _codigo(lineas)
    salida, i = [], 0
    while i < len(lineas):
        if not codigo[i] and lineas[i].lstrip().startswith("|"):
            j = i
            while j < len(lineas) and not codigo[j] and lineas[j].lstrip().startswith("|"):
                j += 1
            salida += _arreglar_tabla(lineas[i:j], cambios)
            i = j
        else:
            salida.append(lineas[i])
            i += 1
    return "\n".join(salida), cambios, quitado


def _clave(texto):
    return re.sub(r"[\W_]", "", texto).lower()


def _plano(ln):
    return ln.strip().strip("*_ ").replace("**", "")


def _proponer_indice(lineas, titulos):
    """Índice impreso: una racha, en el primer cuarto del libro, de líneas que repiten títulos reales."""
    claves = {_clave(t) for t in titulos if _clave(t)}
    mejor, actual, huecos = [], [], 0
    for i, ln in enumerate(lineas[: max(50, len(lineas) // 4)]):
        if not ln.strip():
            continue
        # Sin regex para el final: `[. ]*\d*$` es cuadrático con una racha larga de puntos.
        limpio = re.sub(r"^(?:[-*+]|\d{1,3}\.)\s+", "", ln.strip()).rstrip("0123456789").rstrip(".·… \t")
        if not ln.startswith("#") and _clave(limpio) in claves:
            actual.append(i)
            huecos = 0
        elif actual and huecos < 2 and not ln.startswith("#") and len(ln) < 100:
            huecos += 1
        else:
            mejor, actual, huecos = max(mejor, actual, key=len), [], 0
    mejor = max(mejor, actual, key=len)
    return mejor if len(mejor) >= 5 else []


def es_cabeza(patron):
    """«CAPÍTULO N PUESTA EN MARCHA N»: encabezado de página, con el capítulo y el número de página."""
    m = CAPITULO.fullmatch(patron)
    return m and m.group(3) and m.group(3).endswith(" N")


def proponer(cuerpo, desplazamiento):
    """Lo que requiere criterio, agrupado. Cada propuesta guarda qué líneas toca; el agente solo ve muestras."""
    lineas = cuerpo.split("\n")
    codigo = _codigo(lineas)
    linea = lambda i: i + 1 + desplazamiento  # noqa: E731
    muestras = lambda idx: [{"linea": linea(i), "texto": lineas[i][:100]} for i in idx[:3]]  # noqa: E731
    titulos = [TITULO.fullmatch(ln) for ln in lineas]
    niveles = Counter(len(m.group(1)) for m, c in zip(titulos, codigo) if m and not c)
    texto_titulos = [m.group(2) for m, c in zip(titulos, codigo) if m and not c and len(m.group(1)) in (2, 3)]
    propuestas = []

    indice = _proponer_indice(lineas, texto_titulos)
    en_indice = set(range(indice[0], indice[-1] + 1)) if indice else set()
    if indice:
        propuestas.append({"tipo": "indice_impreso", "linea": linea(indice[0]), "total": len(indice), "muestras": muestras(indice),
                           "accion": "regenerar el índice en ese lugar, con enlaces a los títulos reales",
                           "_rango": [indice[0], indice[-1]]})

    grupos = {}
    for i, ln in enumerate(lineas):
        s = ln.strip()
        if codigo[i] or i in en_indice or not s or len(s) > 120 or s.startswith(("|", "!", ">", "- ")):
            continue
        patron = re.sub(r"\d+", "N", _plano(titulos[i].group(2) if titulos[i] else s))
        # Un título solo entra si es un encabezado de página marcado como <h2>; «### Capítulo 3» es un capítulo.
        if titulos[i] and not es_cabeza(patron):
            continue
        if len(patron) > 3 or patron == "N":
            grupos.setdefault(patron, []).append(i)

    repetidos = {p: idx for p, idx in grupos.items() if len(idx) >= (2 if es_cabeza(p) else MIN_REPETIDAS_NUM if "N" in p else MIN_REPETIDAS)}
    en_repetidas = {i for idx in repetidos.values() for i in idx}
    ordenados = sorted(repetidos.items(), key=lambda x: -len(x[1]))
    # Los encabezados de capítulo no cuentan para el tope: cada uno es un capítulo que se perdería.
    for patron, idx in [g for g in ordenados if es_cabeza(g[0])] + [g for g in ordenados if not es_cabeza(g[0])][:MAX_GRUPOS]:
        p = {"tipo": "lineas_repetidas", "linea": linea(idx[0]), "total": len(idx), "muestras": muestras(idx),
             "accion": "borrar todas las líneas con este patrón (restos de imprenta)", "_quitar": idx, "_patron": patron}
        if es_cabeza(patron):  # el encabezado de página es lo único que nombra el capítulo: la primera vez queda como título
            p["accion"] = "dejar la primera como título ## (sin el número de página) y borrar las demás"
            p["_titulo"] = True
        propuestas.append(p)

    reemplazar, quitar = {}, []
    for i, ln in enumerate(lineas):
        if codigo[i] or i in en_indice or i in en_repetidas or titulos[i] or len(ln) > 120:
            continue
        m = CAPITULO.fullmatch(_plano(ln))
        # Con texto en la misma línea, solo en mayúsculas: «Capítulo 3 explica algo» es una frase.
        if not m or (m.group(3) and (not m.group(1).isupper() or m.group(3).rstrip().endswith((".", ",", ";")))):
            continue
        partes, usados = [_plano(ln)], []
        j = i
        for _ in range(2):
            j = _sig_con_texto(lineas, j)
            if j is None or codigo[j] or j in en_repetidas or len(lineas[j]) > 110 or lineas[j].startswith(("|", "!", "-", ">")):
                break
            sig = titulos[j]
            negrita = lineas[j].strip().startswith("**")
            plano = sig.group(2).strip() if sig else _plano(lineas[j])
            if plano.endswith((".", ",", ";", ":")) or not (sig or negrita or not usados):
                break
            partes.append(plano)
            usados.append(j)
            if not (sig or negrita):
                break
        titulo = partes[0].rstrip(":. ") + (". " + " ".join(partes[1:]) if len(partes) > 1 else "")
        reemplazar[i] = f"## {titulo}"
        quitar += usados
    if reemplazar:
        idx = sorted(reemplazar)
        propuestas.append({"tipo": "capitulo_en_parrafo", "linea": linea(idx[0]), "total": len(idx),
                           "muestras": [{"linea": linea(i), "texto": reemplazar[i][:100]} for i in idx[:3]],
                           "accion": "convertir en títulos ## como los de las muestras", "_reemplazar": {str(k): v for k, v in reemplazar.items()}, "_quitar": quitar})

    usados = en_indice | en_repetidas | set(reemplazar) | set(quitar)
    negrita, mayusculas = {}, {}
    for i, ln in enumerate(lineas):
        s = ln.strip()
        if codigo[i] or i in usados or titulos[i] or not 5 < len(s) <= 94 or s.startswith(("|", "!", ">", "- ", "<")):
            continue
        plano = s.strip("*_ ")
        if len(plano) < 4 or plano.endswith((".", ",", ";", ":")) or NO_ES_SUBTITULO.search(plano):
            continue
        if s.startswith("**") and s.endswith("**") and "**" not in s[2:-2]:
            negrita[i] = plano
        elif "*" not in s and s.isupper() and len(plano.split()) > 2:  # «ISAAC NEWTON», «SÍ»: firmas y rótulos
            mayusculas[i] = plano
    for tipo, grupo in (("subtitulos_negrita", negrita), ("subtitulos_mayusculas", mayusculas)):
        vistos = Counter(_clave(t) for t in grupo.values())
        reemp, sobran, en_parrafo = {}, [], set()
        for i in sorted(grupo):
            if i in sobran:
                continue
            j = _sig_con_texto(lineas, i)
            if i in en_parrafo:
                if j in grupo:
                    en_parrafo.add(j)
                continue
            sig = lineas[j].strip().strip("*_ ") if j is not None else ""
            # Un título partido en dos líneas: «… CON LOS» + «NUEVOS», o «… ESTAMOS HACIENDO» + «MAL ?».
            if j in grupo or (tipo == "subtitulos_mayusculas" and sig.isupper() and len(sig.split()) <= 3):
                if not CONECTOR_FINAL.search(grupo[i]) and len(sig.split()) > 3:
                    en_parrafo.add(j)  # varias seguidas: es un párrafo en negrita o una lista, no títulos
                    continue
                reemp[i], sobran = f"### {grupo[i]} {sig}", sobran + [j]
                continue
            # Un rótulo repetido, una frase que sigue en minúscula o sin párrafo después no es un subtítulo.
            if vistos[_clave(grupo[i])] > 1 or CONECTOR_FINAL.search(grupo[i]) or not sig or sig[0].islower():
                continue
            if tipo == "subtitulos_negrita" and len(sig) < 30:  # una etiqueta seguida de otra línea corta, no un apartado
                continue
            reemp[i] = f"### {grupo[i]}"
        if len(reemp) >= 3:
            idx = sorted(reemp)
            paso = max(1, len(idx) // MUESTRAS_SUBTITULOS)
            propuestas.append({"tipo": tipo, "linea": linea(idx[0]), "total": len(idx),
                               "muestras": [{"linea": linea(i), "texto": reemp[i][4:100]} for i in idx[::paso][:MUESTRAS_SUBTITULOS]],
                               "accion": "convertir en títulos ### todas las líneas de este tipo, salvo las de excluir_lineas",
                               "_reemplazar": {str(k): v for k, v in reemp.items()}, "_quitar": sobran})

    if niveles[2] <= 1 and niveles[3] >= 5:
        propuestas.append({"tipo": "niveles", "linea": linea(0), "total": niveles[3], "muestras": [],
                           "accion": f"subir un nivel los títulos: hay {niveles[2]} ## y {niveles[3]} ###", "_niveles": True})
    for n, p in enumerate(propuestas, 1):
        p["id"] = f"p{n}"
    return propuestas


def _indice_generado(lineas, obsidian):
    codigo = _codigo(lineas)
    salida, vistos = [], Counter()
    for ln, c in zip(lineas, codigo):
        m = TITULO.fullmatch(ln)
        if not m or c or len(m.group(1)) not in (2, 3):
            continue
        texto = m.group(2).strip()
        sangria = "  " if len(m.group(1)) == 3 else ""
        if obsidian:
            limpio = " ".join(re.sub(r"[#|^\[\]]", " ", texto).split())
            salida.append(f"{sangria}- [[#{limpio}]]")
        else:
            ancla = re.sub(r"[^\w\- ]", "", texto.lower()).strip().replace(" ", "-")
            vistos[ancla] += 1
            sufijo = f"-{vistos[ancla] - 1}" if vistos[ancla] > 1 else ""
            salida.append(f"{sangria}- [{texto.replace('[', '(').replace(']', ')')}](#{ancla}{sufijo})")
    return salida


def aplicar_propuestas(cuerpo, aceptadas, excluir=()):
    """Devuelve (texto con marca del índice, palabras quitadas). `excluir`: índices de línea que no se tocan."""
    lineas = cuerpo.split("\n")
    excluir = set(excluir)
    for p in aceptadas:
        if "_reemplazar" in p:
            p["_reemplazar"] = {k: v for k, v in p["_reemplazar"].items() if int(k) not in excluir}
        if "_quitar" in p:
            p["_quitar"] = [i for i in p["_quitar"] if i not in excluir]
    quitar_unir, quitar, reemplazar, quitado = set(), set(), {}, []
    for p in aceptadas:
        if p["tipo"] == "lineas_repetidas":
            quitar_unir.update(p["_quitar"])
            if p.get("_titulo"):
                primera = p["_quitar"][0]
                quitar_unir.discard(primera)
                # El patrón cambió las cifras por N: el título toma las reales, menos la página final.
                sin_pagina = re.sub(r"\s*\d+$", "", _plano(TITULO.sub(r"\2", lineas[primera])))
                quitado.append(re.search(r"\d+\**$", lineas[primera].rstrip()).group(0))
                reemplazar[primera] = f"## {sin_pagina}"
        elif p["tipo"] in ("capitulo_en_parrafo", "subtitulos_negrita", "subtitulos_mayusculas"):
            quitar.update(p["_quitar"])
            reemplazar.update({int(k): v for k, v in p["_reemplazar"].items()})
        elif p["tipo"] == "indice_impreso":
            ini, fin = p["_rango"]
            quitar.update(range(ini + 1, fin + 1))
            quitado.extend(lineas[ini:fin + 1])
            reemplazar[ini] = MARCA_INDICE
    quitado.extend(lineas[i] for i in quitar_unir if i not in quitar)
    # El mismo resto puede ir pegado a un párrafo: «…Uruguay Mi libro (2015).indd 5». Solo patrones largos con cifras.
    pegados = []
    for p in aceptadas:
        partes = re.split(r"\d+", _plano(lineas[p["_quitar"][0]])) if p["tipo"] == "lineas_repetidas" else []
        if len(partes) > 1 and len(p["_patron"]) >= 12:  # desde la línea real: en el patrón, «N» también es la letra de «NOVIEMBRE»
            pegados.append(re.compile(r"\d+".join(map(re.escape, partes))))
    for i, ln in enumerate(lineas):
        if i in quitar_unir or i in quitar or i in reemplazar:
            continue
        for r in pegados:
            if r.search(ln):
                quitado.extend(r.findall(ln))
                ln = " ".join(r.sub(" ", ln).split())
        lineas[i] = ln
    salida, tras_quitado = [], False
    for i, ln in enumerate(lineas):
        if i in quitar_unir:
            tras_quitado = True
            continue
        if i in quitar:
            continue
        ln = reemplazar.get(i, ln)
        if tras_quitado and ln.strip():
            tras_quitado = False
            # Un encabezado de página parte el párrafo en dos: si la frase sigue, se une.
            prev = next((k for k in range(len(salida) - 1, -1, -1) if salida[k].strip()), None)
            if (prev is not None and ln[0].islower() and not salida[prev].startswith(("#", "|", "!", ">", "- "))
                    and not salida[prev].rstrip().endswith(FIN_DE_FRASE)):
                del salida[prev + 1:]
                salida[prev] = salida[prev].rstrip() + " " + ln
                continue
        salida.append(ln)
    if any(p["tipo"] == "niveles" for p in aceptadas):
        codigo = _codigo(salida)
        # El ## único se queda donde está: subirlo daría un segundo # (p. ej., «# Cubierta»).
        salida = [ln[1:] if ln.startswith("###") and not c and TITULO.fullmatch(ln) else ln for ln, c in zip(salida, codigo)]
    return "\n".join(salida), quitado


def _larga(ruta):
    # Un vault profundo más un título largo pasan fácil de 260 caracteres, el límite de Windows sin este prefijo.
    return "\\\\?\\" + os.path.abspath(ruta) if os.name == "nt" and not ruta.startswith("\\\\") else ruta


def _prefijo(front, ruta):
    m = re.search(r'(?m)^title: "(.*)"$', front)
    titulo = m.group(1).replace('\\"', '"') if m else os.path.splitext(os.path.basename(ruta))[0]
    limpio = " ".join(PROHIBIDOS_NOMBRE.sub(" ", titulo).split()).strip(". ")
    return limpio[:80].strip() or "documento"


def empaquetar_obsidian(cuerpo, ruta, front, adjuntos):
    """Copia cada imagen con el título como prefijo y deja `![[…]]`. Devuelve (texto, [(origen, copia)]). Si algo falla, no borra nada."""
    base = os.path.dirname(ruta)
    adjuntos_real = os.path.realpath(os.path.splitext(ruta)[0] + "_adjuntos")
    prefijo = _prefijo(front, ruta)
    destino = os.path.abspath(adjuntos) if adjuntos else os.path.join(base, os.path.splitext(os.path.basename(ruta))[0] + "_adjuntos")
    copias = {}

    def cambiar(m):
        url = urllib.parse.unquote(m.group(1))
        if url.startswith(("http:", "https:", "data:", "\\", "/")) or os.path.isabs(url):
            return m.group(0)  # externa o absoluta: no es nuestra (y consultar \\servidor filtraría el hash NTLM)
        origen = os.path.realpath(os.path.join(base, url))
        # Solo lo que la conversión dejó en su carpeta: el documento no es confiable y `![x](libro.md)` acabaría borrando ese archivo.
        if (not origen.startswith(adjuntos_real + os.sep) or not origen.lower().endswith(EXTENSIONES_IMAGEN)
                or not os.path.isfile(_larga(origen))):
            return m.group(0)
        if origen not in copias:
            nombre = PROHIBIDOS_NOMBRE.sub("_", os.path.basename(origen))
            copias[origen] = nombre if nombre.startswith(prefijo + " - ") else f"{prefijo} - {nombre}"
        alt = " ".join(re.sub(r"[|\[\]]", " ", m.group(0)[2:m.group(0).index("](")]).split())
        return f"![[{copias[origen]}|{alt}]]" if alt else f"![[{copias[origen]}]]"

    texto = calidad.IMAGEN.sub(cambiar, cuerpo)
    hechas = []
    if copias:
        os.makedirs(destino, exist_ok=True)
    for origen, nombre in copias.items():
        copia = os.path.join(destino, nombre)
        if os.path.realpath(copia) != origen:
            with open(_larga(origen), "rb") as f:
                datos = f.read()
            if os.path.exists(_larga(copia)):
                with open(_larga(copia), "rb") as f:
                    if f.read() != datos:  # otro libro con el mismo título: nunca se pisa
                        raise ValueError(f"ya existe otra imagen con el nombre {nombre} en {destino}")
            else:
                with open(_larga(copia), "wb") as f:
                    f.write(datos)
                hechas.append(copia)
    return texto, [(o, os.path.join(destino, n)) for o, n in copias.items()], hechas


def _carpeta_estado(ruta):
    return os.path.join(tempfile.gettempdir(), "todo-a-markdown-pulir", hashlib.sha1(os.path.abspath(ruta).encode("utf-8")).hexdigest()[:16])


def _limpiar_abandonados(raiz, dias=7):
    """Un pulido sin segundo paso deja su copia temporal (texto del libro): no debe quedarse para siempre."""
    if os.path.isdir(raiz):
        for nombre in os.listdir(raiz):
            carpeta = os.path.join(raiz, nombre)
            if time.time() - os.path.getmtime(carpeta) > dias * 86400:
                shutil.rmtree(carpeta, ignore_errors=True)


def _escribir(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)


def _leer(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def _informe(ruta, md, cambios, extra):
    formato = re.search(r'(?m)^format: "(\w+)"$', md)
    evaluado = calidad.evaluar(md, ruta, formato.group(1) if formato else "md", {})
    wikis = [w[3:-2].split("|")[0] for w in WIKI_IMAGEN.findall(md)]
    evaluado["metricas"]["imagenes"] += len(wikis)
    return {"archivo": ruta, "cambios": dict(cambios), **evaluado, **extra}


def _finalizar(ruta, estado, aceptadas, carpeta):
    """Aplica lo aceptado y empaqueta. Ante cualquier fallo restaura el .md original."""
    antes_md = _leer(os.path.join(carpeta, "antes.md"))
    md = _leer(ruta)
    front, cuerpo = _partir(md)
    cuerpo = cuerpo.lstrip("\n")  # los números de línea de las propuestas se calcularon sin la línea en blanco
    creadas = []
    try:
        desplazamiento = front.count("\n") + 1 if front else 0
        nuevo, quitado = aplicar_propuestas(cuerpo, aceptadas, [n - 1 - desplazamiento for n in estado.get("excluir", [])])
        _, antes_cuerpo = _partir(antes_md)
        problema = verificar_fidelidad(antes_cuerpo, nuevo, estado["quitado"] + quitado)
        if problema:
            raise ValueError(problema)
        if MARCA_INDICE in nuevo:
            lineas = nuevo.split("\n")
            generado = _indice_generado(lineas, estado["obsidian"])
            nuevo = nuevo.replace(MARCA_INDICE, "\n".join(generado))
        movidas = []
        if estado["obsidian"]:
            nuevo, movidas, creadas = empaquetar_obsidian(nuevo, ruta, front, estado["adjuntos"])
        _escribir(ruta, _unir(front, limpiar_saltos(nuevo)))
    except (ValueError, OSError) as e:
        _escribir(ruta, antes_md)
        for c in creadas:
            if os.path.exists(_larga(c)):
                os.remove(_larga(c))
        shutil.rmtree(carpeta, ignore_errors=True)
        return {"archivo": ruta, "estado": "error", "error": f"{e}; se restauró el .md original"}
    # Los originales se borran al final: si falla, solo sobra una copia, nunca se pierde una imagen.
    try:
        for origen, copia in movidas:
            if os.path.realpath(copia) != origen and os.path.exists(_larga(origen)):
                os.remove(_larga(origen))
        for carpeta_vieja in {os.path.dirname(o) for o, _ in movidas}:
            if os.path.isdir(carpeta_vieja) and not os.listdir(carpeta_vieja):
                os.rmdir(carpeta_vieja)
    except OSError:
        pass
    shutil.rmtree(carpeta, ignore_errors=True)
    final = _leer(ruta)
    cambios = Counter(estado["cambios"])
    cambios.update({p["tipo"]: p["total"] for p in aceptadas})
    r = _informe(ruta, final, cambios, {})
    roto = [w for w in WIKI_IMAGEN.findall(final) if estado["obsidian"] and not _existe_wiki(w, ruta, estado["adjuntos"])]
    if roto:
        r["estado"] = "revisar"
        r["motivos"].append(f"imagenes_rotas: {len(roto)} imágenes enlazadas no existen (p. ej., {roto[0]})")
    return r


def _existe_wiki(wiki, ruta, adjuntos):
    nombre = wiki[3:-2].split("|")[0]
    # El .md no es confiable: consultar `\\servidor\x` en Windows le enviaría a ese servidor el hash NTLM del usuario.
    if "/" in nombre or "\\" in nombre or ":" in nombre:
        return False
    carpeta = os.path.abspath(adjuntos) if adjuntos else os.path.join(os.path.dirname(ruta), os.path.splitext(os.path.basename(ruta))[0] + "_adjuntos")
    return os.path.isfile(_larga(os.path.join(carpeta, nombre)))


def pulir(ruta, obsidian=False, adjuntos=None):
    ruta = os.path.abspath(ruta)
    if not os.path.isfile(ruta) or not ruta.lower().endswith(".md"):
        return {"archivo": ruta, "estado": "error", "error": "pulir necesita un archivo .md existente"}
    original = _leer(ruta)
    front, cuerpo = _partir(original)
    nuevo, cambios, quitado = corregir_estructura(cuerpo)
    nuevo = limpiar_saltos(nuevo)
    problema = verificar_fidelidad(cuerpo, nuevo, quitado)
    if problema:
        return {"archivo": ruta, "estado": "error", "error": f"{problema}; no se cambió el .md"}
    propuestas = proponer(nuevo, front.count("\n") + 1 if front else 0)
    carpeta = _carpeta_estado(ruta)
    shutil.rmtree(carpeta, ignore_errors=True)  # un pulido anterior que no se terminó
    _limpiar_abandonados(os.path.dirname(carpeta))
    os.makedirs(carpeta)
    _escribir(os.path.join(carpeta, "antes.md"), original)
    md = _unir(front, nuevo)
    _escribir(ruta, md)
    estado = {"obsidian": obsidian, "adjuntos": adjuntos, "cambios": cambios, "quitado": quitado, "propuestas": propuestas,
              "huella": hashlib.sha1(md.encode("utf-8")).hexdigest()}
    if not propuestas:
        return _finalizar(ruta, estado, [], carpeta)
    _escribir(os.path.join(carpeta, "estado.json"), json.dumps(estado, ensure_ascii=False))
    visibles = [{k: v for k, v in p.items() if not k.startswith("_")} for p in propuestas]
    return _informe(ruta, md, cambios, {"estado": "pendiente", "propuestas": visibles})


def aplicar(ruta, ruta_decisiones):
    ruta = os.path.abspath(ruta)
    carpeta = _carpeta_estado(ruta)
    try:
        with open(os.path.join(carpeta, "estado.json"), encoding="utf-8") as f:
            estado = json.load(f)
    except OSError:
        return {"archivo": ruta, "estado": "error", "error": "no hay un pulido pendiente de este .md: ejecuta primero pulir"}
    try:
        with open(ruta_decisiones, encoding="utf-8-sig") as f:
            decisiones = json.load(f)
        ids = decisiones["aceptar"]
        estado["excluir"] = [int(n) for n in decisiones.get("excluir_lineas", [])]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return {"archivo": ruta, "estado": "error", "error": f'decisiones no válidas (se espera {{"aceptar": ["p1"], "excluir_lineas": [120]}}): {e}'}
    por_id = {p["id"]: p for p in estado["propuestas"]}
    desconocidos = [i for i in ids if i not in por_id]
    if desconocidos:
        return {"archivo": ruta, "estado": "error", "error": f"propuestas desconocidas: {desconocidos}"}
    if hashlib.sha1(_leer(ruta).encode("utf-8")).hexdigest() != estado["huella"]:
        return {"archivo": ruta, "estado": "error", "error": "el .md cambió desde el primer paso: ejecuta pulir de nuevo"}
    return _finalizar(ruta, estado, [por_id[i] for i in ids], carpeta)


def main(argv):
    p = argparse.ArgumentParser(prog="todo-a-markdown pulir",
                                description="Corrige la estructura de un .md sin cambiar su texto y devuelve propuestas en JSON.")
    p.add_argument("archivo", help="el .md que se va a pulir")
    p.add_argument("--obsidian", action="store_true", help="imágenes con el título como prefijo y enlaces ![[…]]")
    p.add_argument("--adjuntos", help="con --obsidian: carpeta de las imágenes (por defecto, <nombre>_adjuntos/)")
    p.add_argument("--aplicar", metavar="DECISIONES", help='segundo paso: JSON con {"aceptar": ["p1", …]}; lista vacía si no se acepta ninguna')
    args = p.parse_args(argv)
    r = aplicar(args.archivo, args.aplicar) if args.aplicar else pulir(args.archivo, args.obsidian, args.adjuntos)
    print(json.dumps(r, ensure_ascii=False))
    print(f"[{r['estado']}] {os.path.basename(args.archivo)}", file=sys.stderr)
    return {"ok": 0, "pendiente": 0, "revisar": 1, "error": 2}[r["estado"]]
