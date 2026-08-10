param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))

# Ce script doit être lancé en PowerShell "Exécuter en tant qu'administrateur" :
# le Planificateur de tâches a besoin des droits admin pour accorder au compte
# utilisateur le droit "Ouvrir une session en tant que tâche" (nécessaire au
# LogonType S4U ci-dessous, qui permet aux tâches de tourner sans session
# interactive ouverte, y compris PC verrouillé).

$python  = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$job     = Join-Path $ProjectRoot 'run_job.py'
$appPy   = Join-Path $ProjectRoot 'app.py'

if (-not (Test-Path $python)) { throw "Lancez install.bat avant d'enregistrer les tâches." }
if (-not (Test-Path $pythonw)) {
    Write-Warning "pythonw.exe introuvable dans .venv\Scripts ; le serveur Flask utilisera python.exe (une fenêtre peut apparaître brièvement au démarrage)."
    $pythonw = $python
}

$config = Get-Content (Join-Path $ProjectRoot 'config.json') -Raw | ConvertFrom-Json
$schedule = @($config.schedule)
if ($schedule.Count -ne 4) { throw "config.json doit contenir exactement quatre horaires (00:00, 08:00, 12:00, 16:00)." }

# S4U : la tâche s'exécute que l'utilisateur soit connecté ou non, sans
# fenêtre visible, sans mot de passe stocké. RunLevel Limited suffit car le
# projet n'écrit que dans son propre dossier.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

# --- Tâches de publication (00:00 / 08:00 / 12:00 / 16:00) -------------------
$publishSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

# -WorkingDirectory corrige le "vide" d'origine : sans lui, config.json,
# requirements et chemins relatifs (Images/, Logs/, BaseDeDonnées/) ne se
# résolvaient pas de façon fiable selon le contexte de lancement.
$publishAction = New-ScheduledTaskAction -Execute $python -Argument "`"$job`"" -WorkingDirectory $ProjectRoot

# Le format (vidéo ou déclaration) est déduit du créneau courant dans run_job.py
# via schedule_formats (08:00 & 16:00 → vidéo ; 00:00 & 12:00 → déclaration).
foreach ($time in $schedule) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    Register-ScheduledTask -TaskName "VoixProsperite-$($time.Replace(':',''))" `
        -Action $publishAction -Trigger $trigger -Settings $publishSettings -Principal $principal -Force | Out-Null
}

# --- Rattrapage au démarrage -------------------------------------------------
# Délai de 2 minutes : laisse Windows terminer son démarrage et le réseau
# s'établir avant la première tentative (couvre le cas "Windows démarre avant
# la connexion Internet").
$catchUpAction = New-ScheduledTaskAction -Execute $python -Argument "`"$job`" --catch-up" -WorkingDirectory $ProjectRoot
$catchUpTrigger = New-ScheduledTaskTrigger -AtStartup
$catchUpTrigger.Delay = 'PT2M'
Register-ScheduledTask -TaskName 'VoixProsperite-Rattrapage' `
    -Action $catchUpAction -Trigger $catchUpTrigger -Settings $publishSettings -Principal $principal -Force | Out-Null

# --- Fichiers importés (Format C) toutes les 10 minutes ----------------------
# Vérifie assets/pending et publie aux créneaux manuels définis (ex. 04:00 et
# 20:00, ou un intervalle 1h/2h/3h/4h/6h/12h/1j). Ne fait rien si aucun fichier.
$manualAction = New-ScheduledTaskAction -Execute $python -Argument "`"$job`" --manual" -WorkingDirectory $ProjectRoot
$manualTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'VoixProsperite-Manuel' `
    -Action $manualAction -Trigger $manualTrigger -Settings $publishSettings -Principal $principal -Force | Out-Null

# --- Serveur Flask (interface locale) ---------------------------------------
# pythonw.exe : aucune fenêtre console, contrairement à python.exe.
# ExecutionTimeLimit = 0 : le serveur est censé tourner en continu, pas être
# coupé après un délai. RestartCount élevé : redémarrage auto en cas de crash.
$flaskSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$flaskAction = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$appPy`"" -WorkingDirectory $ProjectRoot
$flaskTrigger = New-ScheduledTaskTrigger -AtStartup
$flaskTrigger.Delay = 'PT1M'
Register-ScheduledTask -TaskName 'VoixProsperite-Serveur' `
    -Action $flaskAction -Trigger $flaskTrigger -Settings $flaskSettings -Principal $principal -Force | Out-Null

Write-Host 'Taches enregistrees :'
Write-Host '  - VoixProsperite-0000 / 0800 / 1200 / 1600 (publication ; format auto par creneau)'
Write-Host '  - VoixProsperite-Manuel (fichiers importes, toutes les 10 min, selon manual_schedule)'
Write-Host '  - VoixProsperite-Rattrapage (au demarrage, delai 2 min)'
Write-Host '  - VoixProsperite-Serveur (interface Flask silencieuse, au demarrage, delai 1 min)'
Write-Host ''
Write-Host 'Toutes les executions sont journalisees dans Logs\scheduler.log (horodatage, commande, duree, succes/echec, traceback).'
