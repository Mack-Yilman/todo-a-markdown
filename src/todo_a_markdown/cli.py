"""todo-a-markdown: convierte documentos a Markdown y emite un informe de calidad en JSON (una línea por archivo)."""

import argparse
import json
import os
import sys
import tempfile
import time
from importlib.metadata import version

from . import calidad, epub, office, pdf
from .comun import frontmatter, hoy, limpiar_saltos, sanitizar

FORMATOS = {
    ".epub": "epub",
    ".pdf": "pdf",
    ".docx": "office", ".pptx": "office", ".xlsx": "office",
    ".html": "office", ".htm": "office", ".csv": "office",
    ".mobi": "calibre", ".azw": "calibre", ".azw3": "calibre", ".fb2": "calibre",
}


def _utf8():
    # La consola de Windows usa CP-1252: sin esto, una tilde o un emoji rompe el print.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _expandir(entradas):
    archivos = []
    for e in entradas:
        if os.path.isdir(e):
            archivos += sorted(os.path.join(e, n) for n in os.listdir(e) if os.path.splitext(n)[1].lower() in FORMATOS)
        else:
            archivos.append(e)
    return archivos


def convertir_archivo(ruta, args):
    t0 = time.time()
    ruta = os.path.abspath(ruta)
    nombre, ext = os.path.splitext(os.path.basename(ruta))
    ext = ext.lower()
    destino = os.path.abspath(args.salida) if args.salida else os.path.dirname(ruta)
    ruta_md = os.path.join(destino, nombre + ".md")
    informe = {"archivo": ruta, "salida": ruta_md, "formato": ext.lstrip(".")}

    if not os.path.isfile(ruta):
        return {**informe, "estado": "error", "error": "el archivo no existe"}
    tipo = FORMATOS.get(ext)
    if not tipo:
        return {**informe, "estado": "error", "error": f"formato no soportado: {ext or 'sin extensión'} (soportados: {', '.join(sorted(FORMATOS))})"}
    if os.path.exists(ruta_md) and not args.sobrescribir:
        return {**informe, "estado": "error", "error": "ya existe un .md con ese nombre; usa --sobrescribir para reemplazarlo"}

    carpeta_rel = nombre + "_adjuntos"
    carpeta_adj = None if args.sin_imagenes else os.path.join(destino, carpeta_rel)
    os.makedirs(destino, exist_ok=True)
    meta = {"title": "", "author": ""}
    fuente, avisos, motor = {}, [], None

    try:
        if tipo in ("epub", "calibre"):
            with tempfile.TemporaryDirectory(prefix="todo-a-markdown-") as tmp:
                origen = office.calibre_a_epub(ruta, tmp) if tipo == "calibre" else ruta
                conv = epub.ConversorEpub(origen, carpeta_adj, carpeta_rel)
                md = conv.convertir()
            meta.update({k: v for k, v in conv.meta.items() if v})
            fuente = {"palabras": conv.palabras_fuente}
            avisos = conv.avisos
            motor = "calibre+epub" if tipo == "calibre" else "epub"
        elif tipo == "pdf":
            fuente = {**pdf.analizar(ruta), "ocr": args.ocr}
            meta.update({k: fuente[k] for k in ("title", "author") if fuente[k]})
            motor = "pymupdf"
            md = pdf.convertir(ruta, carpeta_adj, carpeta_rel, ocr=args.ocr)
        else:
            motor = "markitdown"
            md, titulo = office.convertir(ruta, carpeta_adj, carpeta_rel, nombre)
            meta["title"] = titulo
    except Exception as e:  # cualquier fallo de un motor se informa y el lote sigue
        return {**informe, "estado": "error", "error": f"{type(e).__name__}: {e}"}

    md = sanitizar(md)
    meta["title"] = meta["title"] or nombre
    if not md.lstrip().startswith("# "):
        md = f"# {meta['title']}\n\n{md}"
    md = frontmatter({**meta, "source": os.path.basename(ruta), "format": ext.lstrip("."), "converted": hoy()}) + limpiar_saltos(md)

    with open(ruta_md, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    if carpeta_adj and os.path.isdir(carpeta_adj) and not os.listdir(carpeta_adj):
        os.rmdir(carpeta_adj)

    resultado = calidad.evaluar(md, ruta_md, informe["formato"], fuente)
    resultado["avisos"] = avisos + resultado["avisos"]
    resultado["metricas"]["segundos"] = round(time.time() - t0, 1)
    return {**informe, "motor": motor, **resultado}


def main(argv=None):
    _utf8()
    p = argparse.ArgumentParser(
        prog="todo-a-markdown",
        description="Convierte EPUB, PDF, DOCX, PPTX, XLSX, HTML, CSV, MOBI, AZW3 y FB2 a Markdown para Obsidian y LLM. "
        "Escribe <nombre>.md y <nombre>_adjuntos/ e imprime un informe JSON por archivo en stdout.",
    )
    p.add_argument("entradas", nargs="+", help="archivos o carpetas (de una carpeta se toman los formatos soportados, sin subcarpetas)")
    p.add_argument("-o", "--salida", help="carpeta de salida (por defecto, la del archivo original)")
    p.add_argument("--sin-imagenes", action="store_true", help="no extraer imágenes")
    p.add_argument("--ocr", action="store_true", help="aplicar OCR a las páginas escaneadas de un PDF")
    p.add_argument("--sobrescribir", action="store_true", help="reemplazar el .md si ya existe")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {version('todo-a-markdown')}")
    args = p.parse_args(argv)

    archivos = _expandir(args.entradas)
    if not archivos:
        print("No hay archivos de formatos soportados en las carpetas indicadas.", file=sys.stderr)
        return 2
    # stdout queda solo para el JSON: los motores (pymupdf4llm, RapidOCR) imprimen y registran en stdout.
    salida_json, sys.stdout = sys.stdout, sys.stderr
    pdf.pymupdf.set_messages(stream=sys.stderr)  # pymupdf guardó el stdout original al importarse
    pdf.pymupdf.set_log(stream=sys.stderr)
    codigo = 0
    try:
        for ruta in archivos:
            r = convertir_archivo(ruta, args)
            print(json.dumps(r, ensure_ascii=False), file=salida_json, flush=True)
            print(f"[{r['estado']}] {os.path.basename(ruta)} -> {r['salida']}", file=sys.stderr, flush=True)
            codigo = max(codigo, {"ok": 0, "revisar": 1, "error": 2}[r["estado"]])
    finally:
        sys.stdout = salida_json
    return codigo


if __name__ == "__main__":
    sys.exit(main())
