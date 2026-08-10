Option Explicit
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\Paterne BALAGIZI\Documents\Codex\2026-07-20\cr-e-une-t-che-programm\scripts\sync-github.ps1""", 0, False
