# Instalador de todo-a-markdown (https://github.com/Mack-Yilman/todo-a-markdown).
# Instala la CLI con uv y copia solo la skill (SKILL.md y LICENSE.txt), nunca el resto del repositorio.
#
#   Con menu:  irm https://raw.githubusercontent.com/Mack-Yilman/todo-a-markdown/main/install.ps1 | iex
#   Sin menu:  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Mack-Yilman/todo-a-markdown/main/install.ps1))) -Destino todos -Ocr
#
# Destinos: claude-code, antigravity, descargas, todos. -Ocr instala tambien RapidOCR (PDF escaneados);
# -Docling, el motor para papers a dos columnas (~1,6 GB); -Calibre, para MOBI, AZW3 y FB2 (~700 MB).
# Sin -Destino, el menu pregunta por cada uno. Si falta uv, se instala con winget.
# El archivo es solo ASCII a proposito: los textos con tilde usan \uXXXX (funcion T), asi funciona
# igual en Windows PowerShell 5.1 y PowerShell 7 sin depender de la codificacion. Nunca pases una
# ruta por T: Regex.Unescape fallaria con "\U" de C:\Users.
# Sin [ValidateSet]: con "irm | iex" el param se evalua como variable vacia y la validacion rompe el script.
param([string]$Destino, [switch]$Ocr, [switch]$Docling, [switch]$Calibre)

# Todo corre en un ambito hijo para no dejar variables ni preferencias en la sesion de quien usa "irm | iex".
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $nombre = 'todo-a-markdown'
    $repo = 'Mack-Yilman/todo-a-markdown'
    $zipUrl = "https://github.com/$repo/releases/latest/download/$nombre.zip"
    $rawUrl = "https://raw.githubusercontent.com/$repo/main/skills/$nombre"
    $archivos = 'SKILL.md', 'LICENSE.txt'

    function T([string]$texto) { [regex]::Unescape($texto) }

    function Ruta([string[]]$partes) {
        $ruta = $HOME
        foreach ($parte in $partes) { $ruta = Join-Path $ruta $parte }
        $ruta
    }

    function Get-Descargas {
        if ($env:OS -eq 'Windows_NT') {
            try {
                $ruta = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
                if ($ruta) { return $ruta }
            } catch { }
        }
        Ruta 'Downloads'
    }

    # Descarga la skill en una carpeta temporal: primero la ultima Release; si no la hay, la rama main.
    function Get-Skill {
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("$nombre-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmp | Out-Null
        $zip = Join-Path $tmp "$nombre.zip"
        try {
            Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
        } catch {
            $carpeta = Join-Path $tmp $nombre
            foreach ($archivo in $archivos) {
                $destino = Join-Path $carpeta $archivo
                New-Item -ItemType Directory -Path (Split-Path $destino) -Force | Out-Null
                Invoke-WebRequest -Uri "$rawUrl/$archivo" -OutFile $destino -UseBasicParsing
            }
            Compress-Archive -Path $carpeta -DestinationPath $zip -Force
        }
        $carpeta = Join-Path $tmp $nombre
        if (-not (Test-Path (Join-Path $carpeta 'SKILL.md'))) { throw (T 'No se encontr\u00f3 SKILL.md en la descarga.') }
        [pscustomobject]@{ Temporal = $tmp; Carpeta = $carpeta; Zip = $zip }
    }

    function Write-Hecho([string]$plataforma, [string]$ruta) {
        Write-Host ('  [OK] ' + $plataforma + ' -> ' + $ruta) -ForegroundColor Green
    }

    # La CLI la usan todos los agentes desde la terminal; uv la instala aislada en ~/.local/bin.
    function Install-Cli {
        $extras = @()
        if ($Ocr) { $extras += 'ocr' }
        if ($Docling) { $extras += 'docling' }
        $paquete = if ($extras) { "$nombre[$($extras -join ',')] @ git+https://github.com/$repo" } else { "git+https://github.com/$repo" }
        if (-not (Install-Uv)) {
            Write-Warning ((T 'No pude instalar uv. Inst\u00e1lalo (https://docs.astral.sh/uv/) y ejecuta: uv tool install --python 3.13 --force "') + $paquete + '"')
            return
        }
        Install-Python
        & uv tool install --python 3.13 --force $paquete
        if ($LASTEXITCODE -ne 0) { throw (T 'uv no pudo instalar la CLI.') }
        Install-Lanzador
        # Sin esto, en un equipo sin uv previo el comando no aparece en las sesiones nuevas. Quien fija UV_TOOL_BIN_DIR gestiona su PATH.
        if (-not $env:UV_TOOL_BIN_DIR) { & uv tool update-shell | Out-Host }
        Write-Hecho 'CLI' 'todo-a-markdown'
    }

    # El Python que descarga uv no esta firmado y los antivirus lo interceptan (CyberCapture de Avast); el de winget si lo esta.
    function Install-Python {
        if ([IO.Path]::DirectorySeparatorChar -ne '\') { return }
        $ErrorActionPreference = 'Continue'  # en PowerShell 5.1, el stderr redirigido de un programa cuenta como error
        & uv python find 3.13 --no-python-downloads *> $null
        if ($LASTEXITCODE -eq 0) { return }
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            & winget install --id Python.Python.3.13 --exact --silent --accept-source-agreements --accept-package-agreements | Out-Host
        }
    }

    # El .exe que genera uv no esta firmado y cambia en cada instalacion, asi que los antivirus lo aislan (Autosandbox de Avast).
    # Git Bash usa un lanzador de texto que arranca el python.exe firmado del entorno. PowerShell y cmd usan el .exe: es mas lento con esos
    # antivirus, pero un .cmd no es una alternativa, porque cmd.exe reinterpreta & en %* y un nombre como a&calc&.pdf ejecutaria comandos.
    function Install-Lanzador {
        if ([IO.Path]::DirectorySeparatorChar -ne '\') { return }
        $bin = "$(& uv tool dir --bin)".Trim()
        $python = Join-Path "$(& uv tool dir)".Trim() "$nombre\Scripts\python.exe"
        if (-not (Test-Path $python)) { return }
        $python = $python.Replace('\', '/').Replace("'", "'\''")
        $sinBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText((Join-Path $bin $nombre), "#!/bin/sh`nexec '$python' -m todo_a_markdown `"`$@`"`n", $sinBom)
        Remove-Item (Join-Path $bin "$nombre.cmd") -Force -ErrorAction SilentlyContinue  # lo dejaba la 0.1.2
    }

    function Install-Uv {
        if (Get-Command uv -ErrorAction SilentlyContinue) { return $true }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
        & winget install --id astral-sh.uv --exact --silent --accept-source-agreements --accept-package-agreements | Out-Host
        # winget no refresca el PATH de esta sesion.
        $env:Path = (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links') + [IO.Path]::PathSeparator + $env:Path
        [bool](Get-Command uv -ErrorAction SilentlyContinue)
    }

    # Si falla, la CLI funciona igual con los demas formatos: solo se avisa.
    function Install-Calibre {
        if ((Get-Command ebook-convert -ErrorAction SilentlyContinue) -or (Test-Path "$env:ProgramFiles\Calibre2\ebook-convert.exe")) {
            Write-Hecho 'Calibre' (T 'ya estaba instalado')
            return
        }
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            & winget install --id calibre.calibre --exact --silent --accept-source-agreements --accept-package-agreements | Out-Host
            if ($LASTEXITCODE -eq 0) { Write-Hecho 'Calibre' 'ebook-convert'; return }
        }
        Write-Warning (T 'No pude instalar Calibre. Desc\u00e1rgalo de https://calibre-ebook.com para convertir MOBI, AZW3 y FB2.')
    }

    function Confirmar([string]$pregunta) {
        "$(Read-Host ($pregunta + ' [s/N]'))".Trim() -match '^[sSyY]'
    }

    # Copia la skill en una carpeta de skills. Reemplaza una instalacion anterior, salvo que sea un clon de git.
    function Copy-Skill($skill, [string]$base, [string]$plataforma) {
        $destino = Join-Path $base $nombre
        if (Test-Path (Join-Path $destino '.git')) {
            Write-Warning ((T 'Omitido ') + $plataforma + ': ' + $destino + (T ' es un clon de git; actual\u00edzalo con git pull.'))
            return
        }
        if (Test-Path $destino) { Remove-Item -Path $destino -Recurse -Force }
        New-Item -ItemType Directory -Path $base -Force | Out-Null
        Copy-Item -Path $skill.Carpeta -Destination $destino -Recurse
        Write-Hecho $plataforma $destino
    }

    function Install-Destino($skill, [string]$opcion) {
        switch ($opcion) {
            'claude-code' { Copy-Skill $skill (Ruta '.claude', 'skills') 'Claude Code' }
            # La leen Antigravity IDE y Antigravity CLI (agy).
            'antigravity' { Copy-Skill $skill (Ruta '.gemini', 'config', 'skills') 'Antigravity' }
            'descargas' {
                # Solo se sobrescribe este .zip, nunca se borra nada. La carpeta puede no existir (perfil nuevo).
                $descargas = Get-Descargas
                New-Item -ItemType Directory -Path $descargas -Force | Out-Null
                $zip = Join-Path $descargas "$nombre.zip"
                Copy-Item -Path $skill.Zip -Destination $zip -Force
                Write-Hecho 'Descargas' $zip
                Write-Host (T '       Descompr\u00edmelo en la carpeta de skills de tu agente.')
            }
        }
    }

    $opciones = [ordered]@{
        '1' = 'claude-code'
        '2' = 'antigravity'
        '3' = 'descargas'
        '4' = 'todos'
    }

    Write-Host ''
    Write-Host 'todo-a-markdown: instalador' -ForegroundColor Cyan
    Write-Host (T '  Convierte EPUB, PDF, Word, PowerPoint y Excel a Markdown para Obsidian y LLM.')
    Write-Host ''

    if ($Destino -and -not ($opciones.Values -contains $Destino)) {
        throw ((T 'Destino no v\u00e1lido: ') + $Destino + '. Usa: ' + ($opciones.Values -join ', '))
    }
    if (-not $Destino) {
        Write-Host (T '\u00bfD\u00f3nde quieres instalar la skill? (la CLI se instala siempre)')
        Write-Host '  1) Claude Code'
        Write-Host '  2) Antigravity (IDE y CLI)'
        Write-Host (T '  3) Descargas (.zip para otro LLM con terminal)')
        Write-Host '  4) Todos'
        $eleccion = "$(Read-Host (T 'Escribe un n\u00famero'))".Trim()
        if (-not $opciones.Contains($eleccion)) { throw ((T 'Opci\u00f3n no v\u00e1lida: ') + $eleccion) }
        $Destino = $opciones[$eleccion]
        if (-not $Ocr) { $Ocr = Confirmar (T '\u00bfInstalar OCR para PDF escaneados (~150 MB)?') }
        if (-not $Docling) { $Docling = Confirmar (T '\u00bfInstalar Docling para papers a dos columnas (~1,6 GB)?') }
        if (-not $Calibre) { $Calibre = Confirmar (T '\u00bfInstalar Calibre para MOBI, AZW3 y FB2 (~700 MB)?') }
    }

    Install-Cli
    if ($Calibre) { Install-Calibre }
    $skill = Get-Skill
    try {
        if ($Destino -eq 'todos') {
            foreach ($opcion in 'claude-code', 'antigravity', 'descargas') { Install-Destino $skill $opcion }
        } else {
            Install-Destino $skill $Destino
        }
        Write-Host ''
        Write-Host (T 'Listo. Abre una sesi\u00f3n nueva y pide, por ejemplo: convierte este PDF a markdown.')
        Write-Host (T 'Licencia AGPL-3.0 \u00a9 2026 Mack Chirinos.')
    } finally {
        Remove-Item -Path $skill.Temporal -Recurse -Force -ErrorAction SilentlyContinue
    }
}
