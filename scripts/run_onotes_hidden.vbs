' Hidden-window launcher. Derives its own folder so the project
' can live anywhere (portable / GitHub-friendly). ASCII-only.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & dir & "\run_onotes_scrape.cmd""", 0, False
