"""Entradas hostiles: los regex no deben ser cuadráticos y ebook-convert no se busca en el directorio actual."""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from todo_a_markdown import office, pdf
from todo_a_markdown.comun import limpiar_saltos, quitar_comentarios

N = 2_000_000
TOPE_S = 30  # lineal tarda menos de 2 s; cuadrático con 2 MB, horas

# (expresión que se evalúa con `n`, importada en un proceso aparte para poder cortar un cuelgue)
CASOS = {
    "espacios_sin_salto": "comun.limpiar_saltos('x' + ' ' * n + 'y')",
    "imagen_sin_cierre": "calidad.IMAGEN.sub('', '![' * (n // 2))",
    "imagen_sin_parentesis": "calidad.IMAGEN.sub('', '![](' * (n // 4))",
    "data_uri_sin_cierre": "comun.DATA_URI.sub('', '![' * (n // 2))",
    "data_uri_sin_parentesis": "comun.DATA_URI.sub('', '![](data:image/png;base64,A' * (n // 27))",
    "imagen_pdf_sin_cierre": "pdf.IMAGEN_MD.sub('', '![' * (n // 2))",
    "imagen_pdf_sin_parentesis": "pdf.IMAGEN_MD.sub('', '![](' * (n // 4))",
    "comentarios_sin_cierre": "comun.quitar_comentarios('<!--' * (n // 4))",
    "espacios_sin_comentario": "comun.quitar_comentarios(' ' * n + 'x')",
    "negrita_con_espacios": "pdf._limpiar('**x' + ' ' * n + 'y')",
    "negritas_sin_cierre": "pdf._limpiar('**x ' * (n // 4))",
    "url_sin_espacio": "pdf._limpiar('https://' * (n // 8))",
}


class ReDoS(unittest.TestCase):
    def test_termina_en_tiempo_lineal(self):
        for nombre, expresion in CASOS.items():
            with self.subTest(nombre):
                codigo = f"from todo_a_markdown import calidad, comun, pdf\nn = {N}\n{expresion}\n"
                # TimeoutExpired hace fallar la prueba: subprocess.run mata al hijo antes de relanzarla.
                subprocess.run([sys.executable, "-c", codigo], check=True, capture_output=True, timeout=TOPE_S)


class Equivalencia(unittest.TestCase):
    def test_limpiar_saltos(self):
        self.assertEqual(limpiar_saltos("a  \n\t\n\n\n b\t \nc"), "a\n\n b\nc\n")

    def test_quitar_comentarios(self):
        casos = {
            "a <!-- x --> b": "ab",
            "a\n  <!-- Slide\nnumber: 1 -->  \nb": "a\nb",
            "<!-- x -->\n\nb": "\nb",
            "sin cerrar <!-- x": "sin cerrar <!-- x",
            "a<!-- 1 -->b<!-- 2 -->c": "abc",
            "a --> b": "a --> b",
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada):
                self.assertEqual(quitar_comentarios(entrada), esperado)


    def test_url_partida(self):
        casos = {
            "ver https://doi.org/ 10.1371/x fin": "ver https://doi.org/10.1371/x fin",
            "(https://hdl.handle.net/20. 500.12196/1)": "(https://hdl.handle.net/20.500.12196/1)",
            "https://x.org/ and": "https://x.org/ and",
            "https:// 10.1/x": "https:// 10.1/x",
            "https://a/https:// 10.1/x": "https://a/https://10.1/x",
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada):
                self.assertEqual(pdf._limpiar(entrada), esperado)

    def test_negrita_con_espacio(self):
        casos = {"**Hola **mundo": "**Hola** mundo", "**a b  **c": "**a b** c", "**x **": "**x** ", "**x**": "**x**", "** x **": "** x **"}
        for entrada, esperado in casos.items():
            with self.subTest(entrada):
                self.assertEqual(pdf._limpiar(entrada), esperado)


class BuscarCalibre(unittest.TestCase):
    NOMBRE = "ebook-convert" + (".cmd" if sys.platform == "win32" else "")

    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.actual = os.path.join(carpeta.name, "actual")
        self.instalado = os.path.join(carpeta.name, "instalado")
        for d in (self.actual, self.instalado):
            os.mkdir(d)
            ruta = os.path.join(d, self.NOMBRE)
            with open(ruta, "w") as f:
                f.write("")
            os.chmod(ruta, os.stat(ruta).st_mode | stat.S_IEXEC)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.actual)
        rutas = mock.patch.object(office, "CALIBRE_RUTAS", ())
        rutas.start()
        self.addCleanup(rutas.stop)

    def buscar(self, path):
        with mock.patch.dict(os.environ, {"PATH": path}):
            # Claude Code la define en sus sesiones: sin quitarla, la prueba pasaría aunque el código no la pusiera.
            os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)
            return office.buscar_calibre()

    def test_no_usa_el_directorio_actual(self):
        self.assertIsNone(self.buscar(""))

    def test_no_usa_entradas_relativas_del_path(self):
        self.assertIsNone(self.buscar(os.pathsep.join([".", ""])))

    def test_no_usa_una_subcarpeta_relativa_del_path(self):
        os.mkdir("bin")
        shutil.copy(self.NOMBRE, "bin")
        self.assertIsNone(self.buscar("bin"))

    def test_no_usa_el_directorio_actual_aunque_este_en_el_path(self):
        self.assertIsNone(self.buscar(os.getcwd()))

    def test_lo_encuentra_en_el_path_antes_que_el_plantado(self):
        exe = self.buscar(self.instalado)
        self.assertEqual(os.path.normcase(os.path.dirname(exe)), os.path.normcase(self.instalado))

    def test_prefiere_la_ruta_de_instalacion(self):
        fija = os.path.join(self.instalado, self.NOMBRE)
        with mock.patch.object(office, "CALIBRE_RUTAS", (fija,)):
            self.assertEqual(self.buscar(os.getcwd()), fija)
