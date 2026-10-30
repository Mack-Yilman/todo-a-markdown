"""Post-procesamiento: estructura, propuestas, guardia de fidelidad y empaquetado. Todo con datos inventados."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import unittest.mock

from todo_a_markdown import cli, pulir

import fixtures

TEMPORALES = []
TEMP_ORIGINAL = tempfile.tempdir


def setUpModule():
    # Los pulidos sin terminar de las pruebas no deben dejar sus copias en el temporal del sistema.
    tempfile.tempdir = tempfile.mkdtemp(prefix="tam-pulir-")
    TEMPORALES.append(tempfile.tempdir)


def tearDownModule():
    tempfile.tempdir = TEMP_ORIGINAL
    for d in TEMPORALES:
        shutil.rmtree(d, ignore_errors=True)


def carpeta():
    d = tempfile.mkdtemp(prefix="tam-pulir-")
    TEMPORALES.append(d)
    return d


def correr(*argv):
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(io.StringIO()):
        codigo = cli.main(["pulir", *argv])
    return codigo, json.loads(salida.getvalue())


def crear(texto, nombre="Mi libro.md"):
    d = carpeta()
    ruta = os.path.join(d, nombre)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return ruta


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def decidir(ruta, *ids):
    decisiones = os.path.join(os.path.dirname(ruta), "decisiones.json")
    with open(decisiones, "w", encoding="utf-8") as f:
        json.dump({"aceptar": list(ids)}, f)
    return correr(ruta, "--aplicar", decisiones)


FRONT = '---\ntitle: "Mi libro"\nformat: "epub"\n---\n\n'


class Estructura(unittest.TestCase):
    def test_correcciones_mecanicas(self):
        ruta = crear(FRONT + "# Mi libro\n\n"
                     "## **Título en negrita**\n\nTexto.\n\n"
                     "• Punto uno\n- •Punto dos\n\n"
                     "## Atención y esfuerzo[19]\n\nTexto.\n\n"
                     "## 1\n\n## El método\n\nTexto.\n\n"
                     "## 2. Otro\n\n### 2\n\nTexto.\n\n"
                     "## Apartado [sic]\n\nTexto [19] sin tocar.\n\n"
                     "##\n\nFin.\n")
        codigo, r = correr(ruta)
        md = leer(ruta)
        self.assertEqual((codigo, r["estado"]), (0, "ok"), r)
        for esperado in ("## Título en negrita", "- Punto uno", "- Punto dos", "## Atención y esfuerzo\n", "## 1. El método",
                         "## Apartado [sic]", "Texto [19] sin tocar."):
            self.assertIn(esperado, md)
        self.assertNotIn("### 2", md)
        self.assertNotIn("##\n", md)
        self.assertEqual(r["cambios"]["vinetas"], 2)

    def test_imagen_sale_del_titulo(self):
        d = carpeta()
        os.makedirs(os.path.join(d, "x_adjuntos"))
        ruta = os.path.join(d, "x.md")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(FRONT + "## Capítulo ![](x_adjuntos/a.png)\n\nTexto.\n")
        with open(os.path.join(d, "x_adjuntos", "a.png"), "wb") as f:
            f.write(fixtures.png())
        correr(ruta)
        self.assertIn("## Capítulo\n\n![](x_adjuntos/a.png)", leer(ruta))

    def test_tablas(self):
        ruta = crear(FRONT + "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |\n\n| x | y |\n| 1 | 2 |\n")
        correr(ruta)
        md = leer(ruta)
        self.assertIn("| 1 | 2 |  |", md)
        self.assertIn("| x | y |\n| --- | --- |\n| 1 | 2 |", md)

    def test_no_toca_bloques_de_codigo(self):
        ruta = crear(FRONT + "```\n• literal\n## **no**\n```\n")
        correr(ruta)
        self.assertIn("• literal\n## **no**", leer(ruta))

    def test_titulo_numerico_con_coma_o_dos_puntos(self):
        ruta = crear(FRONT + "### 1\n\nGoogle, te presento a los OKR\n\nTexto.\n\n### 3\n\nOperación Crush:\n\nTexto.\n")
        correr(ruta)
        md = leer(ruta)
        self.assertIn("### 1. Google, te presento a los OKR\n", md)
        self.assertIn("### 3. Operación Crush\n", md)

    def test_titulo_numerico_con_parrafo_largo_no_se_une(self):
        parrafo = "Este es un aforismo largo con punto final que no es ningún título."
        ruta = crear(FRONT + f"## 1\n\n{parrafo}\n")
        correr(ruta)
        self.assertIn(f"## 1\n\n{parrafo}", leer(ruta))


class Propuestas(unittest.TestCase):
    def libro_repetido(self):
        cuerpo = "".join(f"Una frase del libro que sigue\n\nLibro (2015).indd {i}\n\n21/10/15 10:06\n\nen el otro párrafo {i}.\n\n" for i in range(20))
        return crear(FRONT + cuerpo)

    def test_lineas_repetidas_se_agrupan_y_une_el_parrafo(self):
        ruta = self.libro_repetido()
        codigo, r = correr(ruta)
        self.assertEqual((codigo, r["estado"]), (0, "pendiente"))
        grupos = [p for p in r["propuestas"] if p["tipo"] == "lineas_repetidas" and ("indd" in p["muestras"][0]["texto"] or "10:06" in p["muestras"][0]["texto"])]
        self.assertEqual(len(grupos), 2)
        self.assertEqual(grupos[0]["total"], 20)
        self.assertNotIn("_quitar", grupos[0])
        self.assertLessEqual(len(grupos[0]["muestras"]), 3)
        _, r2 = decidir(ruta, *[p["id"] for p in grupos])
        md = leer(ruta)
        self.assertEqual(r2["estado"], "ok", r2)
        self.assertNotIn(".indd", md)
        self.assertIn("Una frase del libro que sigue en el otro párrafo 3.", md)

    def test_resto_pegado_no_toca_letras_n_del_libro(self):
        cuerpo = "".join(f"PAGINA {i} DE NOVIEMBRE\n\nTexto {i}.\n\n" for i in range(9)) + "Fue la PAGINA 3 DE NOVIEMBRE y PAGINA 77 DE MAYO.\n"
        ruta = crear(FRONT + cuerpo)
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if "NOVIEMBRE" in x["muestras"][0]["texto"])
        _, r2 = decidir(ruta, p["id"])
        md = leer(ruta)
        self.assertEqual(r2["estado"], "ok", r2)
        self.assertIn("Fue la y PAGINA 77 DE MAYO.", md)

    def test_rechazar_conserva_el_texto(self):
        ruta = self.libro_repetido()
        correr(ruta)
        _, r = decidir(ruta)
        self.assertEqual(r["estado"], "ok")
        self.assertIn(".indd 7", leer(ruta))

    def test_capitulo_en_parrafo(self):
        ruta = crear(FRONT + "CAPÍTULO 1\n\n**Optimice sus tarjetas**\n\nTexto.\n\n**CAPÍTULO 2**\n\n**nuestras**\n\n## **máquinas**\n\nTexto.\n\nCapítulo 3 explica algo importante\n")
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if x["tipo"] == "capitulo_en_parrafo")
        self.assertEqual(p["total"], 2)
        decidir(ruta, p["id"])
        md = leer(ruta)
        self.assertIn("## CAPÍTULO 1. Optimice sus tarjetas", md)
        self.assertIn("## CAPÍTULO 2. nuestras máquinas", md)
        self.assertIn("Capítulo 3 explica algo importante", md)

    def test_encabezado_de_pagina_deja_el_capitulo(self):
        ruta = crear(FRONT + "".join(f"Texto de la página {i}\n\n**CAPÍTULO 4** PUESTA EN MARCHA **{i}**\n\nque sigue aquí.\n\n" for i in (101, 103, 105)))
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if x["tipo"] == "lineas_repetidas" and "CAPÍTULO" in x["muestras"][0]["texto"])
        _, r2 = decidir(ruta, p["id"])
        md = leer(ruta)
        self.assertEqual(r2["estado"], "ok", r2)
        self.assertEqual(md.count("## CAPÍTULO 4 PUESTA EN MARCHA"), 1)
        self.assertNotIn("**103**", md)
        self.assertNotIn("PUESTA EN MARCHA 101", md)
        self.assertIn("Texto de la página 103 que sigue aquí.", md)

    def test_etiqueta_de_capitulo_se_une_a_su_titulo(self):
        ruta = crear(FRONT + "## Capítulo 6\n\nEL CUERPO INTERIOR\n\nTexto largo del capítulo, con varias frases.\n")
        correr(ruta)
        self.assertIn("## Capítulo 6. EL CUERPO INTERIOR\n", leer(ruta))

    PARRAFO = "Este es un párrafo normal del libro con bastante texto para que parezca cuerpo.\n\n"

    def test_subtitulos(self):
        ruta = crear(FRONT + "".join(f"**Sección de prueba {i}**\n\n{self.PARRAFO}OTRO RÓTULO LARGO {i}\n\n{self.PARRAFO}" for i in range(4)))
        _, r = correr(ruta)
        tipos = {p["tipo"]: p for p in r["propuestas"]}
        decidir(ruta, tipos["subtitulos_negrita"]["id"])
        md = leer(ruta)
        self.assertIn("### Sección de prueba 2", md)
        self.assertNotIn("### OTRO", md)

    def test_subtitulos_descartan_lo_que_no_lo_es(self):
        falsos = ("**ISBN: 978-84-92921-30-0**", "ISAAC NEWTON", "SÍ", "**NirAndFar.com/Indistractable**", "**1. Metaaprendizaje: Dibuja un mapa**",
                  "QUISIERA AGRADECER A MIS PACIENTES, QUE COMPARTIERON SUS\n\nexperiencias y reflexiones durante años de consulta y mucho más.",
                  "POR MARC ALLEN Y OTROS")
        reales = "".join(f"**Sección real {i}**\n\n{self.PARRAFO}" for i in range(3))
        ruta = crear(FRONT + reales + "".join(f"{f}\n\n{self.PARRAFO}" for f in falsos) + "**Fila uno de un párrafo**\n\n**Fila dos de un párrafo**\n\n**Fila tres de un párrafo**\n\n" + self.PARRAFO)
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if x["tipo"] == "subtitulos_negrita")
        self.assertEqual(p["total"], 3, p)
        self.assertFalse([x for x in r["propuestas"] if x["tipo"] == "subtitulos_mayusculas"])

    def test_subtitulo_partido_se_une(self):
        ruta = crear(FRONT + "".join(f"LA INTERFERENCIA NÚMERO {i} CON LOS\n\nNUEVOS\n\n{self.PARRAFO}" for i in range(3)))
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if x["tipo"] == "subtitulos_mayusculas")
        decidir(ruta, p["id"])
        self.assertIn("### LA INTERFERENCIA NÚMERO 1 CON LOS NUEVOS\n", leer(ruta))

    def test_excluir_lineas(self):
        ruta = crear(FRONT + "".join(f"**Sección real {i}**\n\n{self.PARRAFO}" for i in range(4)))
        _, r = correr(ruta)
        p = r["propuestas"][0]
        d = os.path.join(os.path.dirname(ruta), "d.json")
        with open(d, "w", encoding="utf-8") as f:
            json.dump({"aceptar": [p["id"]], "excluir_lineas": [p["muestras"][1]["linea"]]}, f)
        _, r2 = correr(ruta, "--aplicar", d)
        md = leer(ruta)
        self.assertEqual(r2["estado"], "ok", r2)
        self.assertIn("**Sección real 1**", md)
        self.assertIn("### Sección real 2", md)

    def test_niveles(self):
        ruta = crear(FRONT + "## Único\n\n" + "".join(f"### Parte {i}\n\nTexto {i}.\n\n" for i in range(6)))
        _, r = correr(ruta)
        p = next(x for x in r["propuestas"] if x["tipo"] == "niveles")
        decidir(ruta, p["id"])
        md = leer(ruta)
        self.assertIn("## Parte 3", md)
        self.assertNotIn("# Único\n", md.replace("## Único", ""))  # el ## no pasa a ser un segundo #

    def indice(self, *opciones):
        nombres = [f"Tema número {i}" for i in range(6)]
        cuerpo = "## Contenido\n\n" + "\n".join(f"{n} {i + 10}" for i, n in enumerate(nombres)) + "\n\n"
        cuerpo += "".join(f"## {n}\n\nTexto largo.\n\n" for n in nombres)
        ruta = crear(FRONT + cuerpo)
        _, r = correr(ruta, *opciones)
        p = next(x for x in r["propuestas"] if x["tipo"] == "indice_impreso")
        decidir(ruta, p["id"])
        return leer(ruta)

    def test_indice_obsidian(self):
        md = self.indice("--obsidian")
        self.assertIn("- [[#Tema número 2]]", md)
        self.assertNotIn("Tema número 2 12", md)

    def test_indice_estandar(self):
        md = self.indice()
        self.assertIn("- [Tema número 2](#tema-número-2)", md)
        self.assertNotIn("[[", md)


class Guardia(unittest.TestCase):
    def test_autoriza_solo_lo_quitado(self):
        self.assertIsNone(pulir.verificar_fidelidad("uno **dos** tres", "uno dos tres", []))
        self.assertIsNone(pulir.verificar_fidelidad("uno dos tres", "uno tres", ["dos"]))
        self.assertIn("faltan", pulir.verificar_fidelidad("uno dos tres", "uno tres", []))
        self.assertIn("sobran", pulir.verificar_fidelidad("uno dos", "uno dos tres", []))
        self.assertIn("orden", pulir.verificar_fidelidad("uno dos tres", "tres dos uno", []))

    def test_fallo_restaura_y_no_deja_copia(self):
        ruta = crear(FRONT + "## 1\n\n## Título\n\n" + "Libro.indd 1\n\n" * 0 + "".join(f"pie {i}\n\n" for i in range(9)))
        original = leer(ruta)
        correr(ruta)
        real = pulir.verificar_fidelidad
        pulir.verificar_fidelidad = lambda *a: "guardia de fidelidad: falló"
        try:
            codigo, r = decidir(ruta, "p1")
        finally:
            pulir.verificar_fidelidad = real
        self.assertEqual((codigo, r["estado"]), (2, "error"))
        self.assertEqual(leer(ruta), original)
        self.assertFalse(os.path.exists(pulir._carpeta_estado(ruta)))

    def test_no_queda_copia_temporal_al_terminar(self):
        ruta = crear(FRONT + "Texto.\n")
        correr(ruta)
        self.assertFalse(os.path.exists(pulir._carpeta_estado(ruta)))
        ruta = crear(FRONT + "".join(f"pie {i}\n\n" for i in range(9)))
        correr(ruta)
        self.assertTrue(os.path.exists(pulir._carpeta_estado(ruta)))
        decidir(ruta)
        self.assertFalse(os.path.exists(pulir._carpeta_estado(ruta)))

    def test_copias_abandonadas_se_borran(self):
        ruta = crear(FRONT + "".join(f"pie {i}\n\n" for i in range(9)))
        correr(ruta)
        vieja = pulir._carpeta_estado(ruta)
        os.utime(vieja, (time.time() - 8 * 86400,) * 2)
        correr(crear(FRONT + "Texto.\n"))
        self.assertFalse(os.path.exists(vieja))

    def test_id_desconocido_y_md_editado(self):
        ruta = crear(FRONT + "".join(f"pie {i}\n\n" for i in range(9)))
        correr(ruta)
        self.assertEqual(decidir(ruta, "p99")[0], 2)
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("nota del usuario\n")
        _, r = decidir(ruta, "p1")
        self.assertIn("cambió", r["error"])
        self.assertIn("nota del usuario", leer(ruta))

    def test_aplicar_sin_pulir(self):
        ruta = crear(FRONT + "Texto.\n")
        self.assertIn("pendiente", decidir(ruta)[1]["error"])

    def test_regex_lineales(self):
        for ataque in ("![" * 500_000, "![[" * 300_000, "# " + " " * 1_000_000 + "x", "| " * 500_000, "**" * 500_000, "." * 1_000_000 + "x"):
            ruta = crear(FRONT + ataque + "\n")
            t0 = time.time()
            correr(ruta)
            self.assertLess(time.time() - t0, 20, ataque[:5])


class Obsidian(unittest.TestCase):
    def libro(self):
        d = carpeta()
        ruta = os.path.join(d, "Mi libro.md")
        adj = os.path.join(d, "Mi libro_adjuntos")
        os.makedirs(adj)
        with open(os.path.join(adj, "portada 1.png"), "wb") as f:
            f.write(fixtures.png())
        with open(ruta, "w", encoding="utf-8") as f:
            f.write('---\ntitle: "Un: libro?"\n---\n\nTexto.\n\n![Nefrona](Mi%20libro_adjuntos/portada%201.png)\n')
        return d, ruta, adj

    def test_prefijo_y_wikilink(self):
        _, ruta, adj = self.libro()
        _, r = correr(ruta, "--obsidian")
        self.assertEqual(r["estado"], "ok", r)
        self.assertIn("![[Un libro - portada 1.png|Nefrona]]", leer(ruta))
        self.assertEqual(os.listdir(adj), ["Un libro - portada 1.png"])
        self.assertEqual(r["metricas"]["imagenes"], 1)

    def test_carpeta_de_adjuntos_elegida(self):
        d, ruta, adj = self.libro()
        destino = os.path.join(d, "vault", "adjuntos")
        _, r = correr(ruta, "--obsidian", "--adjuntos", destino)
        self.assertEqual(r["estado"], "ok", r)
        self.assertEqual(os.listdir(destino), ["Un libro - portada 1.png"])
        self.assertFalse(os.path.exists(adj))

    def test_no_pisa_imagen_ajena(self):
        d, ruta, adj = self.libro()
        destino = os.path.join(d, "adj")
        os.makedirs(destino)
        with open(os.path.join(destino, "Un libro - portada 1.png"), "wb") as f:
            f.write(b"otra")
        original = leer(ruta)
        codigo, r = correr(ruta, "--obsidian", "--adjuntos", destino)
        self.assertEqual(codigo, 2, r)
        self.assertEqual(leer(ruta), original)
        self.assertTrue(os.path.exists(os.path.join(adj, "portada 1.png")))

    def test_ruta_fuera_del_libro_no_se_copia(self):
        d = carpeta()
        ruta = os.path.join(d, "sub", "x.md")
        os.makedirs(os.path.dirname(ruta))
        with open(os.path.join(d, "secreto.png"), "wb") as f:
            f.write(b"x")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(FRONT + "![](../secreto.png)\n\n![](//servidor/a.png)\n")
        _, r = correr(ruta, "--obsidian")
        self.assertEqual(r["estado"], "revisar")
        self.assertNotIn("![[", leer(ruta))
        self.assertFalse(os.path.exists(os.path.join(d, "sub", "x_adjuntos")))

    def test_enlace_malicioso_no_borra_archivos_ajenos(self):
        d, ruta, adj = self.libro()
        privado = os.path.join(d, "privado.txt")
        for p in (privado, os.path.join(adj, "datos.txt")):
            with open(p, "w", encoding="utf-8") as f:
                f.write("no tocar")
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("\n![x](privado.txt)\n\n![y](Mi%20libro.md)\n\n![z](Mi%20libro_adjuntos/datos.txt)\n")
        correr(ruta, "--obsidian")
        self.assertTrue(os.path.exists(privado))
        self.assertTrue(os.path.exists(os.path.join(adj, "datos.txt")))
        self.assertIn("![y](Mi%20libro.md)", leer(ruta))

    def test_wikilink_a_servidor_no_se_consulta(self):
        with unittest.mock.patch("os.path.isfile", side_effect=AssertionError("consultó la ruta")):
            self.assertFalse(pulir._existe_wiki("![[\\\\atacante\\s\\i.png]]", "C:/x/a.md", None))
            self.assertFalse(pulir._existe_wiki("![[../../secreto.png]]", "C:/x/a.md", None))

    def test_fallo_al_borrar_el_origen_no_pierde_nada(self):
        _, ruta, adj = self.libro()
        with unittest.mock.patch("os.remove", side_effect=PermissionError("bloqueado")):
            _, r = correr(ruta, "--obsidian")
        self.assertEqual(r["estado"], "ok", r)
        self.assertEqual(sorted(os.listdir(adj)), ["Un libro - portada 1.png", "portada 1.png"])

    def test_estandar_no_usa_sintaxis_de_obsidian(self):
        _, ruta, adj = self.libro()
        correr(ruta)
        self.assertIn("![Nefrona](Mi%20libro_adjuntos/portada%201.png)", leer(ruta))
        self.assertEqual(os.listdir(adj), ["portada 1.png"])


class Regresiones(unittest.TestCase):
    """Causas raíz de epub.py."""

    def convertir(self, cuerpos, toc):
        d = carpeta()
        ruta = os.path.join(d, "x.epub")
        with open(ruta, "wb") as f:
            f.write(fixtures.epub_a_medida(cuerpos, toc))
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(io.StringIO()):
            cli.main([ruta])
        return leer(os.path.join(d, "x.md"))

    def test_ancla_dentro_de_parrafo_es_titulo(self):
        md = self.convertir({"a.xhtml": '<p><a id="c1"></a>Texto de apertura.</p><p>Otro.</p>'}, [("Capítulo uno", "a.xhtml#c1"), ("Dos", "a.xhtml#c2")])
        self.assertIn("\n## Capítulo uno\n", md)
        self.assertNotIn("\\##", md)
        self.assertIn("Texto de apertura.", md)

    def test_retorno_de_carro(self):
        md = self.convertir({"a.xhtml": "<p>Uno.</p>\r\n\r\n\r\n<p>Dos.</p>&#13;\n<p>Tres.</p>"}, [("Solo", "a.xhtml")])
        self.assertNotIn("\r", md)
        self.assertNotIn("\n\n\n", md)

    def test_lista_anidada_no_se_aplana(self):
        md = self.convertir({"a.xhtml": "<ol><li>Parte uno<ol><li>Tema A</li><li>Tema B</li></ol></li><li>Parte dos</li></ol>"}, [("Solo", "a.xhtml")])
        self.assertIn("1. Parte uno\n   1. Tema A\n   2. Tema B\n2. Parte dos", md)

    def test_titulo_dentro_de_un_item_conserva_su_linea(self):
        md = self.convertir({"a.xhtml": "<ol><li><p>Nota uno.</p><h2>Capítulo 5</h2><ol><li>Nota dos.</li></ol></li></ol>"}, [("Solo", "a.xhtml")])
        self.assertIn("1. Nota uno.", md)
        self.assertIn("\n## Capítulo 5\n", md)
        self.assertIn("Nota dos.", md)

    def test_titulo_del_toc_mas_largo_absorbe_el_del_cuerpo(self):
        md = self.convertir({"a.xhtml": '<p id="c1">Prólogo</p><p>Texto.</p>'}, [("Prólogo de Ana", "a.xhtml#c1"), ("Otro", "a.xhtml#c2")])
        self.assertIn("## Prólogo de Ana\n\nTexto.", md)

    def test_frase_corta_bajo_un_titulo_no_se_borra(self):
        md = self.convertir({"a.xhtml": '<p id="c1">La casa.</p><p>Texto.</p>'}, [("La casa de Bernarda", "a.xhtml#c1"), ("Otro", "a.xhtml#c2")])
        self.assertIn("La casa.", md)

    def test_hash_no_es_titulo(self):
        d = carpeta()
        ruta = os.path.join(d, "Mi libro.epub")
        with open(ruta, "wb") as f:
            f.write(fixtures.epub_a_medida({"a.xhtml": "<p>Hola.</p>"}, [("x", "a.xhtml")], titulo="e2e0cb991771f786c745a34974000e77"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main([ruta])
        self.assertIn("# Mi libro", leer(os.path.join(d, "Mi libro.md")))

    def test_toc_sin_ancla(self):
        md = self.convertir({"a.xhtml": "<p>Texto de A.</p>", "b.xhtml": "<h2>Capítulo B</h2><p>Texto.</p>",
                             "c.xhtml": "<p>Capítulo C</p><p>Texto de C.</p>", "d.xhtml": '<img src="x.png"/>'},
                            [("Capítulo A", "a.xhtml"), ("Capítulo B", "b.xhtml"), ("Capítulo C", "c.xhtml"), ("Portada", "d.xhtml")])
        self.assertIn("## Capítulo A\n\nTexto de A.", md)
        self.assertEqual(md.count("Capítulo B"), 1)
        self.assertEqual(md.count("Capítulo C"), 1)
        self.assertIn("## Capítulo C", md)
        self.assertNotIn("Portada", md)


if __name__ == "__main__":
    unittest.main()
