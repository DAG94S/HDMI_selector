param(
    [string]$TaskName = 'AutoScreensaverHdmi',
    [int]$PollSeconds = 5,
    [int]$ScreensaverTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'AutoScreensaverHdmi.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "No existe el script principal: $scriptPath"
}

$powerShell = Join-Path $PSHOME 'powershell.exe'
$arguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-WindowStyle', 'Hidden',
    '-File', "`"$scriptPath`"",
    '-PollSeconds', $PollSeconds,
    '-ScreensaverTimeoutSeconds', $ScreensaverTimeoutSeconds
) -join ' '

$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Activa o desactiva el protector de pantalla segun si solo esta activa la salida HDMI.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

[pscustomobject]@{
    TaskName = $TaskName
    Script = $scriptPath
    Status = 'Registrada e iniciada'
}
