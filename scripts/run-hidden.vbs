' run-hidden.vbs - Execute a command with no visible window.
' Usage (ad-hoc, à partir d'un terminal) :
'   wscript run-hidden.vbs "cmd /c your command"
'   wscript run-hidden.vbs "powershell -NoProfile -WindowStyle Hidden -File script.ps1"
'
' IMPORTANT (règle PC) : pour les TÂCHES PLANIFIÉES, ne pas passer par ce
' fichier avec une longue chaîne entre guillemets-l'imbrication de guillemets
' posera problème. Utiliser plutôt un launcher .vbs dédié, généré par
' register-background-task.ps1 (commande codée en dur, aucune atteinte de
' guillemets). Ce fichier n'est que le lanceur ponctuel masqué.
'
' Window style 0 = hidden, bWaitOnReturn = False (fire and forget, sans attente).
Option Explicit
Dim shell, cmd
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then
    WScript.Echo "Usage: wscript run-hidden.vbs ""command to run"""
    WScript.Quit 1
End If
cmd = WScript.Arguments(0)
shell.Run cmd, 0, False