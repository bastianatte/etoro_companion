# Giro giornaliero del trader autonomo. Lanciato dall'Utilità di pianificazione di Windows.
# Log in logs\AAAA-MM-GG.log ; diario in journal\AAAA-MM-GG.md
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force "$root\logs" | Out-Null
$log = "$root\logs\$(Get-Date -Format 'yyyy-MM-dd').log"

if (Test-Path "$root\STOP") {
    "$(Get-Date -Format s) File STOP presente: giro saltato." | Out-File -Append -Encoding utf8 $log
    exit 0
}

# token di lunga durata per i lavori automatici (claude setup-token), salvato in .env
foreach ($line in Get-Content -Encoding utf8 "$root\.env") {
    if ($line -match '^\s*CLAUDE_CODE_OAUTH_TOKEN\s*=\s*(.+)$') { $env:CLAUDE_CODE_OAUTH_TOKEN = $Matches[1].Trim() }
}

$prompt = Get-Content -Raw -Encoding utf8 "$root\agent\DAILY_PROMPT.md"
$claude = "$env:USERPROFILE\.local\bin\claude.exe"

"=== $(Get-Date -Format s) inizio giro ===" | Out-File -Append -Encoding utf8 $log
& $claude -p "Esegui il giro giornaliero di oggi ($(Get-Date -Format 'yyyy-MM-dd'))." `
    --append-system-prompt $prompt `
    --permission-mode dontAsk `
    --allowedTools "WebSearch" "WebFetch" "Bash(python -m trader.cli:*)" "Read" "Glob" "Grep" "Edit(journal/**)" `
    --disallowedTools "Read(./.env)" "Read(**/.env)" `
    --no-session-persistence 2>&1 | Out-File -Append -Encoding utf8 $log
"=== $(Get-Date -Format s) fine giro (exit $LASTEXITCODE) ===" | Out-File -Append -Encoding utf8 $log
