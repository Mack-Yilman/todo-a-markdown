import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest

from todo_a_markdown import calidad, cli
from todo_a_markdown.comun import extraer_data_uris, frontmatter, sanitizar

import fixtures

TEMPORALES = []


def tearDownModule():
    for d in TEMPORALES:
        shutil.rmtree(d, ignore_errors=True)


def carpeta():
    d = tempfile.mkdtemp(prefix="tam-prueba-")
    TEMPORALES.append(d)
    return d


def correr(*argv):
    """Ejecuta la CLI y devuelve (código, lista de informes JSON)."""
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(io.StringIO()):
        codigo = cli.main(list(argv))
    return codigo, [json.loads(ln) for ln in salida.getvalue().splitlines() if ln.strip()]


def escribir(directorio, nombre, datos):
    ruta = os.path.join(directorio, nombre)
    with open(ruta, "wb") as f:
        f.write(datos)
    return ruta


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


class Epub(unittest.TestCase):
    def convertir(self, con_ncx=True):
        d = carpeta()
        ruta = escribir(d, "Mi libro.epub", fixtures.epub(con_ncx))
        codigo, [r] = correr(ruta)
        return codigo, r, leer(r["salida"]), d

    def test_capitulos_desde_ncx_y_metadatos(self):
        codigo, r, md, _ = self.convertir()
        self.assertEqual((codigo, r["estado"]), (0, "ok"), r)
        self.assertIn("## Capítulo uno", md)
        self.assertIn("## Capítulo dos", md)
        self.assertIn('title: "Libro de prueba"', md)
        self.assertIn('author: "Autora Inventada"', md)
        self.assertTrue(md.startswith("---\n"))

    def test_sin_titulos_repetidos_ni_sangria(self):
        _, _, md, _ = self.convertir()
        self.assertEqual(md.lower().count("capítulo dos"), 1, md)  # TOC «Capítulo dos» + cuerpo «CAPÍTULO DOS»
        self.assertIn("- Uno\n- Dos", md)
        self.assertNotRegex(md, r"(?m)^ {4}\S")  # 4 espacios = bloque de código en Markdown

    def test_capitulos_desde_nav_epub3(self):
        _, r, md, _ = self.convertir(con_ncx=False)
        self.assertIn("## Capítulo uno", md)
        self.assertEqual(r["metricas"]["titulos"].get("h2"), 2)

    def test_sanitiza_para_obsidian(self):
        _, r, md, _ = self.convertir()
        self.assertNotIn("[[1]]", md)
        self.assertIn("(1)", md)
        self.assertIn("josephsoninstitute[.]org", md)
        self.assertEqual(r["metricas"]["wikilinks_falsos"], 0)

    def test_imagen_relativa_que_existe(self):
        _, r, md, d = self.convertir()
        self.assertIn("![Nefrona](Mi%20libro_adjuntos/figura_1.png)", md)
        self.assertTrue(os.path.exists(os.path.join(d, "Mi libro_adjuntos", "figura_1.png")))
        self.assertEqual(r["metricas"]["imagenes_rotas"], 0)

    def test_formato_basico(self):
        _, _, md, _ = self.convertir()
        self.assertIn("La **fisiología** del riñón", md)
        self.assertIn("Primer bloque\n\nSegundo bloque", md)
        self.assertIn("| Amoxicilina | 500 mg |", md)
        self.assertIn("1. Primero\n2. Segundo", md)
        self.assertIn("*No hay devoluciones*", md)  # dos <i> seguidos: un solo énfasis
        self.assertIn("corazón, señal", md)

    def test_ratio_de_palabras_cercano_a_uno(self):
        _, r, _, _ = self.convertir()
        self.assertGreaterEqual(r["metricas"]["ratio"], 0.9)

    def test_sin_imagenes(self):
        d = carpeta()
        ruta = escribir(d, "libro.epub", fixtures.epub())
        _, [r] = correr(ruta, "--sin-imagenes")
        self.assertNotIn("![", leer(r["salida"]))
        self.assertFalse(os.path.exists(os.path.join(d, "libro_adjuntos")))


class Pdf(unittest.TestCase):
    def test_pdf_con_texto(self):
        d = carpeta()
        ruta = escribir(d, "guia.pdf", fixtures.pdf())
        codigo, [r] = correr(ruta)
        md = leer(r["salida"])
        self.assertEqual(r["estado"], "ok", r)
        self.assertEqual(r["motor"], "pymupdf")
        self.assertIn("hipertensión arterial", md)
        self.assertIn('title: "Guía inventada de hipertensión"', md)
        self.assertEqual(r["metricas"]["paginas"], 3)
        self.assertNotIn("C:/", md.replace("\\", "/"))  # sin rutas absolutas
        self.assertNotIn("<!--", md)

    def test_imagenes_relativas_y_sin_vinetas(self):
        d = carpeta()
        ruta = escribir(d, "guia.pdf", fixtures.pdf())
        _, [r] = correr(ruta)
        self.assertEqual(r["metricas"]["imagenes"], 1, r)
        self.assertEqual(r["metricas"]["imagenes_rotas"], 0)
        self.assertIn("](guia_adjuntos/", leer(r["salida"]))

    def test_dos_columnas_pide_docling(self):
        d = carpeta()
        _, [r] = correr(escribir(d, "paper.pdf", fixtures.pdf(dos_columnas=True)), "--sin-imagenes")
        self.assertTrue(any(m.startswith("dos_columnas") for m in r["motivos"]), r)
        _, [r] = correr(escribir(d, "simple.pdf", fixtures.pdf()), "--sin-imagenes")
        self.assertFalse(any(m.startswith("dos_columnas") for m in r["motivos"]), r)

    def test_limpieza_de_urls_y_negritas(self):
        from todo_a_markdown.pdf import _limpiar
        self.assertEqual(_limpiar("ver https://hdl.handle.net/20. 500.12196/CIDACS/65, y"),
                         "ver https://hdl.handle.net/20.500.12196/CIDACS/65, y")
        self.assertEqual(_limpiar("https://doi.org/ 10.1371/journal.pmed"), "https://doi.org/10.1371/journal.pmed")
        self.assertEqual(_limpiar("visita https://x.org/ and more"), "visita https://x.org/ and more")
        self.assertEqual(_limpiar("|**BFP **|"), "|**BFP** |")

    def test_metadatos_solo_si_aparecen_en_el_texto(self):
        from todo_a_markdown.pdf import metadatos_confiables
        md = "# Características de los artículos\n\nPAMO REYNA Oscar, TURÍN RAMOS Elizabeth\n\nTexto."
        self.assertEqual(metadatos_confiables({"title": "REVISTA MEDICA HEREDIANA VOL", "author": "JAIME FARFAN"}, md), {})
        self.assertEqual(metadatos_confiables({"title": "Características de los artículos", "author": "Pamo Reyna Oscar; Turín"}, md),
                         {"title": "Características de los artículos", "author": "Pamo Reyna Oscar; Turín"})

    def test_restaura_guiones_entre_numeros(self):
        from todo_a_markdown.pdf import guiones_de_fin_de_linea, restaurar_guiones
        original = ("Anales 1996; 57 (3): 158-\n173. Un método de bias-\ncorrection y la bias-correction usual; "
                    "para image-\nand transform storage; un trata-\nmiento largo.")
        pares = guiones_de_fin_de_linea(original)
        md = "Anales 1996; 57 (3): 158173. Año 2015158173. Un biascorrection; imageand transform; tratamiento."
        self.assertEqual(restaurar_guiones(md, pares),
                         "Anales 1996; 57 (3): 158-173. Año 2015158173. Un bias-correction; image- and transform; tratamiento.")

    def test_sobrescribir_no_deja_imagenes_huerfanas(self):
        d = carpeta()
        ruta = escribir(d, "guia.pdf", fixtures.pdf())
        correr(ruta)
        escribir(os.path.join(d, "guia_adjuntos"), "vieja.png", fixtures.png())
        correr(ruta, "--sobrescribir")
        self.assertNotIn("vieja.png", os.listdir(os.path.join(d, "guia_adjuntos")))

    def test_quita_texto_vertical(self):
        from todo_a_markdown.pdf import _limpiar
        sello = "\n\n".join("OpMahvoR")
        self.assertEqual(_limpiar(f"# Título\n\n{sello}\n\nTexto del paper."), "# Título\n\nTexto del paper.")
        lista = "- a\n- b\n- c"
        self.assertEqual(_limpiar(lista), lista)  # pocas líneas cortas: se quedan

    def test_barra_lateral_en_una_pagina(self):
        import pymupdf
        doc = pymupdf.open()
        for _ in range(2):
            pag = doc.new_page()
            for y in (60, 260, 460):  # barra lateral angosta a la izquierda y texto principal a la derecha
                pag.insert_textbox(pymupdf.Rect(40, y, 170, y + 190), fixtures.PARRAFO * 2, fontsize=8)
                pag.insert_textbox(pymupdf.Rect(200, y, 560, y + 190), fixtures.PARRAFO * 3, fontsize=10)
        _, [r] = correr(escribir(carpeta(), "lateral.pdf", doc.tobytes()), "--sin-imagenes")
        self.assertTrue(any(m.startswith("dos_columnas: hay columnas o una barra lateral en las páginas 1, 2")
                            for m in r["motivos"]), r["motivos"])

    def test_formulas_de_docling_quedan_marcadas_y_avisadas(self):
        from todo_a_markdown.pdf import _limpiar
        md = _limpiar("Texto\n\n<!-- formula-not-decoded -->\n\nmás texto")
        self.assertIn("[fórmula no convertida", md)
        r = calidad.evaluar("# T\n\n" + md, os.path.join(carpeta(), "n.md"), "pdf", {})
        self.assertTrue(any(m.startswith("formulas_omitidas: 1") for m in r["motivos"]), r)

    @unittest.skipUnless(importlib.util.find_spec("docling"), "Docling no instalado (extra opcional)")
    def test_docling_en_dos_columnas(self):
        d = carpeta()
        _, [r] = correr(escribir(d, "paper.pdf", fixtures.pdf(dos_columnas=True)), "--motor", "docling")
        self.assertEqual(r["motor"], "docling")
        # Docling ordena las columnas, pero el informe pide revisar esas páginas (no promete un orden perfecto).
        self.assertEqual([m.split(":")[0] for m in r["motivos"]], ["columnas"], r)
        self.assertIn("hipertensión arterial", leer(r["salida"]))

    def test_escaneado_pide_ocr(self):
        d = carpeta()
        ruta = escribir(d, "escaneo.pdf", fixtures.pdf(paginas=2, escaneado=True))
        codigo, [r] = correr(ruta, "--sin-imagenes")
        self.assertEqual((codigo, r["estado"]), (1, "revisar"))
        self.assertTrue(any(m.startswith("escaneado") for m in r["motivos"]), r["motivos"])

    def test_pdf_danado_es_error_y_el_lote_sigue(self):
        d = carpeta()
        malo = escribir(d, "roto.pdf", b"esto no es un pdf")
        bueno = escribir(d, "libro.epub", fixtures.epub())
        codigo, informes = correr(malo, bueno)
        self.assertEqual(codigo, 2)
        self.assertEqual([r["estado"] for r in informes], ["error", "ok"])


class Office(unittest.TestCase):
    def test_docx_titulos_tabla_e_imagen(self):
        d = carpeta()
        ruta = os.path.join(d, "protocolo.docx")
        fixtures.docx(ruta)
        _, [r] = correr(ruta)
        md = leer(r["salida"])
        self.assertEqual(r["estado"], "ok", r)
        self.assertIn("# Protocolo inventado", md)
        self.assertIn("## Objetivos", md)
        self.assertIn("Lactato", md)
        self.assertNotIn("base64", md)
        self.assertIn("| Variable | Valor |\n| --- | --- |\n| Lactato |", md)  # sin fila de encabezado vacía
        self.assertEqual(r["metricas"]["imagenes"], 1)
        self.assertEqual(r["metricas"]["imagenes_rotas"], 0)

    def test_pptx_y_xlsx(self):
        d = carpeta()
        fixtures.pptx(os.path.join(d, "clase.pptx"))
        fixtures.xlsx(os.path.join(d, "datos.xlsx"))
        codigo, informes = correr(d)  # una carpeta entera
        self.assertEqual(codigo, 0, informes)
        textos = {os.path.basename(r["archivo"]): leer(r["salida"]) for r in informes}
        self.assertIn("Betabloqueantes", textos["clase.pptx"])
        self.assertNotIn("<!--", textos["clase.pptx"])
        self.assertEqual(len(re.findall(r"(?m)^# ", textos["clase.pptx"])), 1)
        self.assertIn("## Clase de farmacología", textos["clase.pptx"])
        self.assertIn('title: "datos"', textos["datos.xlsx"])  # no «Sheet», el nombre de la hoja
        self.assertIn("Caso A", textos["datos.xlsx"])


class Errores(unittest.TestCase):
    def test_archivo_inexistente(self):
        codigo, [r] = correr(os.path.join(carpeta(), "no-existe.pdf"))
        self.assertEqual((codigo, r["estado"]), (2, "error"))
        self.assertIn("no existe", r["error"])

    def test_formato_no_soportado(self):
        ruta = escribir(carpeta(), "notas.odt", b"x")
        _, [r] = correr(ruta)
        self.assertIn("formato no soportado", r["error"])

    def test_no_pisa_un_md_existente(self):
        d = carpeta()
        ruta = escribir(d, "libro.epub", fixtures.epub())
        escribir(d, "libro.md", "mis notas en Obsidian".encode())
        _, [r] = correr(ruta)
        self.assertEqual(r["estado"], "error")
        self.assertEqual(leer(os.path.join(d, "libro.md")), "mis notas en Obsidian")
        _, [r] = correr(ruta, "--sobrescribir")
        self.assertEqual(r["estado"], "ok")

    def test_salida_en_otra_carpeta(self):
        d, destino = carpeta(), os.path.join(carpeta(), "vault", "Libros")
        ruta = escribir(d, "libro.epub", fixtures.epub())
        _, [r] = correr(ruta, "-o", destino)
        self.assertTrue(r["salida"].startswith(destino))
        self.assertTrue(os.path.exists(os.path.join(destino, "libro_adjuntos")))

    def test_stdout_del_proceso_es_solo_json(self):
        # En un proceso real: pymupdf guarda el stdout al importarse y redirect_stdout no lo ve.
        import subprocess
        import sys
        d = carpeta()
        ruta = escribir(d, "guia.pdf", fixtures.pdf())
        proc = subprocess.run([sys.executable, "-m", "todo_a_markdown.cli", ruta, "--ocr"],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
        lineas = proc.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(lineas), 1, proc.stdout[:300])
        self.assertIn(json.loads(lineas[0])["estado"], ("ok", "error"))

    def test_carpeta_sin_documentos(self):
        codigo, informes = correr(carpeta())
        self.assertEqual((codigo, informes), (2, []))


class Comun(unittest.TestCase):
    def test_sanitizar(self):
        self.assertEqual(sanitizar("texto^[[12]] y [[3]]"), "texto(12) y (3)")
        self.assertEqual(sanitizar("[[Nota real]]"), "[[Nota real]]")

    def test_frontmatter_escapa_comillas(self):
        fm = frontmatter({"title": 'El "mejor" libro: parte 1', "author": ""})
        self.assertIn('title: "El \\"mejor\\" libro: parte 1"', fm)
        self.assertNotIn("author", fm)

    def test_data_uri_a_archivo(self):
        import base64
        d = carpeta()
        md = f"![logo](data:image/png;base64,{base64.b64encode(fixtures.png()).decode()})"
        res = extraer_data_uris(md, os.path.join(d, "x_adjuntos"), "x_adjuntos", "x")
        self.assertEqual(res, "![logo](x_adjuntos/x-001.png)")
        self.assertTrue(os.path.exists(os.path.join(d, "x_adjuntos", "x-001.png")))


class Acentos(unittest.TestCase):
    def test_une_acentos_sueltos_de_latex(self):
        from todo_a_markdown.pdf import unir_acentos
        self.assertEqual(unir_acentos("Bolsa Famı´lia, Gonc¸alo, O¨ zler y CadU<sup>´</sup> nico"),
                         "Bolsa Família, Gonçalo, Özler y CadÚnico")
        # variantes de Docling: acento separado por espacios, a veces ya aplicado a la letra
        self.assertEqual(unir_acentos("Famí ´ lia, Integraç ¸ ão, Luı ´ s, Cadastro U ´ nico, Saú ´ de"),
                         "Família, Integração, Luís, Cadastro Único, Saúde")
        self.assertEqual(unir_acentos("para Sau´ ´ de (CIDACS)"), "para Saúde (CIDACS)")  # acento repetido

    def test_no_toca_apostrofos_ni_texto_normal(self):
        from todo_a_markdown.pdf import unir_acentos
        for texto in ("I don´t know", "canción ñandú", "it´s", "5 ´ 3", "who´s there", "I´m here", "we´ve"):
            self.assertEqual(unir_acentos(texto), texto)


class Calidad(unittest.TestCase):
    def evaluar(self, md, fuente=None, formato="epub"):
        return calidad.evaluar(md, os.path.join(carpeta(), "n.md"), formato, fuente or {})

    def test_mojibake(self):
        r = self.evaluar("# T\n\nLa canciÃ³n del coraÃ³n y la niÃ±a")
        self.assertEqual(r["estado"], "revisar")
        self.assertTrue(r["motivos"][0].startswith("mojibake"))

    def test_simbolos_ilegibles_son_aviso_con_contexto(self):
        r = self.evaluar("# T\n\nEdad (\ufffd5 años)")
        self.assertEqual(r["estado"], "ok")
        self.assertIn("5 años", r["avisos"][0])

    def test_ocr_siempre_pide_revision(self):
        r = self.evaluar("# T\n\ntexto leído con OCR", {"paginas": 2, "paginas_sin_texto": 2, "palabras": 0, "ocr": True}, "pdf")
        self.assertEqual(r["estado"], "revisar")
        self.assertTrue(r["motivos"][0].startswith("ocr:"))

    def test_texto_perdido(self):
        r = self.evaluar("# T\n\nuna dos tres", {"palabras": 100})
        self.assertTrue(any(m.startswith("texto_perdido") for m in r["motivos"]))

    def test_imagen_rota(self):
        r = self.evaluar("# T\n\n![](adjuntos/falta.png)")
        self.assertTrue(any(m.startswith("imagenes_rotas") for m in r["motivos"]))

    def test_documento_largo_sin_titulos(self):
        r = self.evaluar("palabra " * 4000)
        self.assertTrue(any(m.startswith("sin_titulos") for m in r["motivos"]))

    def test_lineas_repetidas_en_pdf(self):
        md = "# T\n\n" + "\n\n".join(["Revista Inventada 2026; 1(2)", "texto distinto %d" % i][i % 2] for i in range(20))
        r = self.evaluar(md, {"paginas": 10, "paginas_sin_texto": 0}, "pdf")
        self.assertTrue(any(a.startswith("lineas_repetidas") for a in r["avisos"]))


CORPUS = os.path.join(os.path.dirname(__file__), "..", "ejemplos", "corpus")


@unittest.skipUnless(os.path.isdir(CORPUS), "corpus local ausente (normal en CI)")
class CorpusReal(unittest.TestCase):
    def test_epub_reales_ok(self):
        libros = [os.path.join(CORPUS, n) for n in os.listdir(CORPUS) if n.endswith(".epub")]
        codigo, informes = correr(*libros, "-o", carpeta(), "--sin-imagenes")
        for r in informes:
            self.assertEqual(r["estado"], "ok", r)
            self.assertGreaterEqual(r["metricas"]["titulos"].get("h2", 0), 10)


if __name__ == "__main__":
    unittest.main()
