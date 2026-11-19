' Hidden-window launcher. Derives its own folder so the project
' can live anywhere (portable / GitHub-friendly). ASCII-only.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
sh.Run """" & dir & "\run_server.cmd""", 0, False
