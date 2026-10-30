# todo-a-markdown

Convierte libros y documentos a **Markdown limpio para Obsidian y para LLM**, y te dice qué tan confiable salió cada conversión.

| Formato | Motor |
|---|---|
| EPUB | Conversor propio: capítulos desde el índice del libro, imágenes y notas al pie sin enlaces rotos |
| PDF | [pymupdf4llm](https://github.com/pymupdf/pymupdf4llm): columnas, tablas y títulos; sin encabezados ni pies de página |
| Paper a dos columnas o con tablas exigentes | [Docling](https://github.com/docling-project/docling) de IBM (opcional): respeta el orden de las columnas y las tablas |
| PDF escaneado | pymupdf4llm con OCR de [RapidOCR](https://github.com/RapidAI/RapidOCR) (opcional) |
| DOCX, PPTX, XLSX, HTML, CSV | [MarkItDown](https://github.com/microsoft/markitdown) de Microsoft, con las imágenes extraídas |
| MOBI, AZW, AZW3, FB2 | [Calibre](https://calibre-ebook.com) los pasa a EPUB (debe estar instalado) |

Son dos piezas:

- **La CLI `todo-a-markdown`** convierte y emite un informe de calidad por archivo.
- **La skill** enseña a tu agente a usar la CLI, leer el informe, reintentar con otras opciones cuando hace falta, revisar el resultado por muestreo y explicarte en lenguaje simple qué revisar. No resume ni reescribe tu documento.

Todo corre en tu equipo; nada se sube a internet. Funciona en un portátil de 8 GB sin tarjeta gráfica.

## Instalación

### Todo de una vez (Windows)

En PowerShell:

```powershell
irm https://raw.githubusercontent.com/Mack-Yilman/todo-a-markdown/main/install.ps1 | iex
```

Instala la CLI con [uv](https://docs.astral.sh/uv/) y te pregunta dónde copiar la skill: Claude Code, Antigravity (IDE y CLI), Descargas o todos. Sin menú y con OCR:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Mack-Yilman/todo-a-markdown/main/install.ps1))) -Destino todos -Ocr -Docling
```

### Solo la CLI

```bash
uv tool install git+https://github.com/Mack-Yilman/todo-a-markdown
# con OCR para PDF escaneados:
uv tool install "todo-a-markdown[ocr] @ git+https://github.com/Mack-Yilman/todo-a-markdown"
# con Docling para papers a dos columnas (ocupa ~1,6 GB):
uv tool install "todo-a-markdown[docling] @ git+https://github.com/Mack-Yilman/todo-a-markdown"
# los dos extras: [ocr,docling]
# sin uv:
python -m pip install --user git+https://github.com/Mack-Yilman/todo-a-markdown
```

Necesita Python 3.11 o superior (uv lo descarga si no lo tienes).

### Solo la skill

Es para **Claude Code o cualquier otro LLM con terminal**, porque ejecuta la CLI.

- **Varios agentes a la vez:** `npx skills add Mack-Yilman/todo-a-markdown`
- **Claude Code:** descomprime [todo-a-markdown.zip](https://github.com/Mack-Yilman/todo-a-markdown/releases/latest/download/todo-a-markdown.zip) en `~/.claude/skills/`.
- **Antigravity (IDE y CLI):** descomprímelo en `~/.gemini/config/skills/`.
- **Claude.ai, Desktop y Cowork:** Configuración › Capacidades › Skills › sube el `.zip`. Solo funciona donde el agente tiene terminal.
- **Pidiéndoselo a tu agente:** «Instala la skill de https://github.com/Mack-Yilman/todo-a-markdown: copia la carpeta `skills/todo-a-markdown` en tu carpeta de skills e instala la CLI con `uv tool install git+https://github.com/Mack-Yilman/todo-a-markdown`».

## Uso

Con la skill, pídeselo a tu agente con tus palabras:

> Convierte este PDF a markdown y guárdalo en mi vault, en la carpeta Libros.

Desde la terminal:

```bash
todo-a-markdown "Mi libro.epub"                      # crea Mi libro.md y Mi libro_adjuntos/ al lado
todo-a-markdown paper.pdf -o "C:/Vault/Papers"       # en otra carpeta
todo-a-markdown carpeta-con-documentos/              # todos los formatos soportados de una carpeta
todo-a-markdown escaneado.pdf --ocr                  # PDF escaneado (requiere el extra [ocr])
todo-a-markdown paper.pdf --motor docling            # paper a dos columnas (requiere el extra [docling])
todo-a-markdown apuntes.docx --sin-imagenes          # solo el texto
```

Nunca reemplaza un `.md` que ya existe (podría tener tus notas) salvo que agregues `--sobrescribir`.

### El resultado

```text
Mi libro.md            # frontmatter (title, author, source, format, converted) + el contenido
Mi libro_adjuntos/     # imágenes, enlazadas con rutas relativas
```

Las imágenes usan enlaces Markdown estándar (`![](Mi%20libro_adjuntos/figura.png)`), que Obsidian y cualquier visor entienden.

### El informe de calidad

Por cada archivo, la CLI imprime una línea JSON en la salida estándar (y una línea legible en la de errores):

```json
{"archivo": "...paper.pdf", "salida": "...paper.md", "formato": "pdf", "motor": "pymupdf", "estado": "ok",
 "motivos": [], "avisos": ["simbolos_ilegibles: 7 caracteres � (símbolos como ≤, ≥ o ± sin Unicode en el original); p. ej., «Primary school or less (�5 years»"],
 "metricas": {"palabras": 8111, "palabras_fuente": 9307, "ratio": 0.871, "titulos": {"h1": 1, "h2": 15, "h3": 6}, "imagenes": 2, "paginas": 17, "segundos": 12.3}}
```

- **`estado`:** `ok`, `revisar` (hay `motivos`: texto perdido, mojibake, imágenes rotas, PDF escaneado sin OCR, documento largo sin títulos) o `error`.
- **`avisos`:** lo que conviene revisar aunque el estado sea `ok`, como símbolos que el original no guarda bien, páginas leídas con OCR o encabezados repetidos.
- **Código de salida:** 0 si todo está `ok`, 1 si hay algún `revisar` y 2 si hay algún `error`.

## Limitaciones conocidas

- **Símbolos sin Unicode:** algunos PDF guardan `≤`, `≥`, `±` o letras griegas con fuentes sin código de texto. Ningún extractor los recupera; salen como `�` y el informe lo avisa con un ejemplo para que lo revises en el original.
- **OCR:** RapidOCR lee bien el español, pero puede equivocarse en cifras, dosis, nombres y tablas, y mezclar columnas. Por eso un PDF leído con OCR siempre sale en `revisar`.
- **Ecuaciones:** Docling no convierte las ecuaciones a texto; cada una queda marcada como «[fórmula no convertida]» y el informe las cuenta. La notación matemática dentro de las frases puede salir desordenada.
- **Autor de un PDF:** se toma de los metadatos del archivo, que a veces dicen quién armó el PDF y no quién escribió el artículo.
- **Encabezados y pies de página:** casi siempre se quitan, pero alguno puede quedar en medio de un párrafo.
- **Dos columnas:** el motor por defecto (pymupdf4llm) es rápido, pero a veces intercala las columnas de un paper. El informe lo detecta (`dos_columnas`) y la skill reconvierte con Docling, que las ordena bien pero tarda unos 10 s por página (un paper de 17 páginas: ~2 min en un portátil de 8 GB, con 1,5 GB de RAM).
- No convierte páginas web por URL. Para eso usa [Defuddle](https://github.com/kepano/defuddle).

## Desarrollo

```bash
uv sync --extra ocr --extra docling
uv run python -m unittest discover -s tests
```

`ejemplos/checklist.md` es la checklist de calidad con la que se revisa cada versión.

## Licencia

[AGPL-3.0-or-later](LICENSE) © 2026 Mack Chirinos. PyMuPDF, el motor de PDF, es AGPL, y esta licencia lo respeta: puedes usar, modificar y distribuir este proyecto, pero si distribuyes una versión modificada o la ofreces como servicio en red, debes publicar su código con la misma licencia.
