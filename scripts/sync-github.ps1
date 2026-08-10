<#
  sync-github.ps1 — Synchronisation automatique du dépôt local vers GitHub (main).

  Comportement :
  1. git add -A (ajoute toutes les modifications).
  2. Garde-fou anti-secrets : si un motif de jeton/clé/mot de passe est
     détecté dans les changements en attente, le script s'arrête (exit 1)
     et consigne les détails dans Logs\push-error.log.
  3. Commit horodaté puis push de master vers main.

  Prérequis : dépôt initialisé, remote origin configuré,
  credential.helper configuré (Windows Credential Manager).
#>
[CmdletBinding()]
param(
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$logDir = Join-Path $root 'Logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$errLog = Join-Path $logDir 'push-error.log'

function Write-Log([string]$msg) {
    Add-Content -LiteralPath $errLog -Value ("{0}  {1}" -f (Get-Date -Format s), $msg)
}

# 1) Indexer tous les changements
git add -A 2>$null
$status = git status --porcelain
if (-not $status) {
    'Rien à synchroniser (dépôt à jour).'
    exit 0
}

# 2) Garde-fou anti-secrets (ne JAMAIS pousser un secret en dur)
$patterns = @(
    'ghp_[0-9A-Za-z]{20,}',
    'github_pat_[0-9A-Za-z_]{20,}',
    'xox[baprs]-[0-9A-Za-z-]{20,}',
    'AIza[0-9A-Za-z_-]{35}',
    'EAAG[0-9A-Za-z]{25,}',
    'sk-[0-9A-Za-z]{20,}',
    'sk-ant-[0-9A-Za-z_-]{20,}',
    'AKIA[0-9A-Z]{16}',
    '-----BEGIN [A-Z ]*PRIVATE KEY-----',
    '(password|passwd|client_secret|api[_-]?key|access[_-]?token)\s*[=:]\s*[''][^'']{8,}['']'
)
$staged = git diff --cached 2>$null
$bad = $staged | Select-String -Pattern $patterns
if ($bad) {
    Write-Log 'ABORT : motif sensible détecté dans les changements en attente — rien n a ete pousse.'
    $bad | Select-Object -First 20 | ForEach-Object {
        $line = $_.Line.Trim()
        if ($line.Length -gt 160) { $line = $line.Substring(0, 160) + '...' }
        Write-Log ('   -> ' + $line)
    }
    Write-Output "ABORT : secret détecté dans les fichiers en attente. Détails : $errLog"
    exit 1
}

# 3) Commit + push
$msg = 'sync: mise à jour automatique (' + (Get-Date -Format 'yyyy-MM-dd HH:mm') + ')'
git commit -m $msg 2>&1 | Out-Null
$pushOut = git push origin master:main 2>&1
$pushOut | Out-String | ForEach-Object { Write-Log $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Output "ECHEC du push (code $LASTEXITCODE). Détails : $errLog"
    exit 1
}
Write-Output ('OK : synchronisé le ' + (Get-Date -Format 'yyyy-MM-dd HH:mm'))
exit 0
