' Pjsk radar: start the local site server with a HIDDEN window.
' Called by run_server.cmd (which already checked the port is free).
' Must start python DIRECTLY -- calling run_server.cmd again would create
' an infinite cmd<->vbs recursion (the site would never come up).
' Derives its own folder so the project can live anywhere. ASCII-only.
Set fso = CreateObject("Scripting.FileSystemObject")
scripts = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(scripts)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Run "py -X utf8 server\server.py", 0, False
