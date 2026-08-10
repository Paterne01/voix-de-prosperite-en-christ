<#
  register-background-task.ps1 - Create a scheduled task that runs a script
  in the BACKGROUND (non-interactive, no console window ever appears).

  Why: a normal scheduled task opens a console window that flashes on the
  desktop. Using a non-interactive principal (S4U) makes Windows run it in a
  hidden session with no visible window at all.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File register-background-task.ps1 `
        -TaskName "MySync" -ScriptPath "C:\path\script.ps1" `
        -RepeatMinutes 5 [-UseVbs]

  -TaskName      : unique task name (required)
  -ScriptPath    : absolute path to the .ps1 or .bat to run (required)
  -RepeatMinutes : run every N minutes, indefinitely (default 5)
  -UseVbs        : wrap with scripts\run-hidden.vbs as an extra safety layer
                   (recommended for .bat files)

  Verify later with:  Get-ScheduledTask -TaskName "MySync"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [ValidateRange(1, 1440)][int]$RepeatMinutes = 5,
    [switch]$UseVbs
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script introuvable : $ScriptPath"
}

$vbs = Join-Path $PSScriptRoot 'run-hidden.vbs'
$ext = [System.IO.Path]::GetExtension($ScriptPath).ToLowerInvariant()

if ($UseVbs -or $ext -eq '.bat' -or $ext -eq '.cmd') {
    # Wrap via WScript so no console is ever created.
    $wrapped = "$vbs `"$ScriptPath`""
    $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$wrapped`""
} else {
    # PowerShell script: hidden window style + non-interactive session.
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
}

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $RepeatMinutes)

# S4U = run as the current user WITHOUT an interactive session (no window,
# no password stored). This is the key to silent background execution.
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Force | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
"OK : tâche '$TaskName' enregistrée en arrière-plan (non-interactive)."
"  Principal : $($t.Principal.LogonType) / $($t.Principal.UserId)"
"  Action    : $($t.Actions.Execute) $($t.Actions.Arguments)"
"  Répétition: toutes les $RepeatMinutes min, indéfiniment."
