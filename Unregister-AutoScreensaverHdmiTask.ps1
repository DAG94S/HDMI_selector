param(
    [string]$TaskName = 'AutoScreensaverHdmi'
)

$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    [pscustomobject]@{
        TaskName = $TaskName
        Status = 'No existia'
    }
    exit
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

[pscustomobject]@{
    TaskName = $TaskName
    Status = 'Eliminada'
}
