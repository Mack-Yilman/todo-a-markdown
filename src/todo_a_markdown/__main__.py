"""`python -m todo_a_markdown`: arranca con el python.exe firmado, sin el .exe sin firmar que genera uv."""

import sys

from .cli import main

sys.exit(main())
