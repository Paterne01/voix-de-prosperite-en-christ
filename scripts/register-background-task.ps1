<#
  register-background-task.ps1 - Create a scheduled task that runs a script
  in the BACKGROUND with no console window ever appearing.

  Why: a scheduled task launching powershell.exe or .bat directly opens a
  console window that flashes on the desktop. Instead we generate a dedicated
  launcher .vbs whose whole job is to start the command via
  WScript.Shell.Run(..., 0, False) in a hidden window, then schedule
  wscript.exe (a GUI-subsystem process that never creates a console) to run it.
  Result: zero visible window, no admin rights required.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File register-background-task.ps1 `
        -TaskName "MySync" -ScriptPath "C:\path\script.ps1" -RepeatMinutes 5

  -TaskName      : unique task name (required)
  -ScriptPath    : absolute path to the .ps1 or .bat/.cmd to run (required)
  -RepeatMinutes : run every N minutes, indefinitely (default 5)

  The launcher is written to <thisScriptsDir>\launchers\<TaskName>.vbs.
  Re-registering the same TaskName overwrites the existing task and launcher.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [ValidateRange(1, 1440)][int]$RepeatMinutes = 5
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script introuvable : $ScriptPath"
}

# 1) Générer un launcher VBS dédié (commande codée en dur : aucun problème
#    d'imbrication de guillemets au moment du lancement).
$ext = [System.IO.Path]::GetExtension($ScriptPath).ToLowerInvariant()
if ($ext -eq '.bat' -or $ext -eq '.cmd') {
    $inner = '"' + $ScriptPath + '"'
} else {
    $inner = 'powershell -NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '"'
}
# Échapper les guillemets pour la syntaxe VBS (chaque " devient "").
$innerVbs = $inner -replace '"', '""'

$launcherDir = Join-Path $PSScriptRoot 'launchers'
if (-not (Test-Path -LiteralPath $launcherDir)) {
    New-Item -ItemType Directory -Path $launcherDir | Out-Null
}
$safeName = $TaskName -replace '[\\/:*?"<>| ]', '_'
$vbsPath = Join-Path $launcherDir ($safeName + '.vbs')

$vbsContent = @"
Option Explicit
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run "$innerVbs", 0, False
"@
Set-Content -LiteralPath $vbsPath -Value $vbsContent -Encoding ASCII

# 2) Action de la tâche = wscript.exe + launcher (wscript n'ouvre jamais de
#    console, la fenêtre est donc totalement invisible).
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"' + $vbsPath + '"')

# 3) Se déclenche 1 minute après la création, puis toutes les N minutes.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $RepeatMinutes)

# Principal par défaut = utilisateur courant, session interactive légère.
# Inutile de demander S4U (décès droits admin) : wscript.exe suffit.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Force | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
"OK : tâche '$TaskName' enregistrée en arrière-plan (aucune fenêtre)."
"  Launcher : $vbsPath"
"  Action   : $($t.Actions.Execute) $($t.Actions.Arguments)"
"  Répétition : toutes les $RepeatMinutes min, indéfiniment."
"  Test rapide : Start-ScheduledTask -TaskName '$TaskName'"