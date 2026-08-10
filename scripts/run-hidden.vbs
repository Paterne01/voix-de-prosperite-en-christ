' run-hidden.vbs - Execute a command with no visible window.
' Usage:  wscript run-hidden.vbs "cmd /c your command"
'         wscript run-hidden.vbs "powershell -NoProfile -WindowStyle Hidden -File script.ps1"
' Window style 0 = hidden, bWaitOnReturn = False (fire and forget).
Option Explicit
Dim shell, cmd
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then
    WScript.Echo "Usage: wscript run-hidden.vbs ""command to run"""
    WScript.Quit 1
End If
cmd = WScript.Arguments(0)
shell.Run cmd, 0, False
