Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\diego\Scripts\AutoScreensaverHdmi.ps1"" -ScreensaverTimeoutSeconds 120", 0, True
