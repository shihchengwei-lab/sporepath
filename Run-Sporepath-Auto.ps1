$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

& "$PSScriptRoot\Start-ArcRift.bat"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$env:PYTHONPATH = "src"
$env:ARCRIFT_DB = Join-Path $PSScriptRoot "..\ArcRift\backend\ArcRift.db"
$env:SPOREPATH_DB = "real_memory.sqlite"
$env:SPOREPATH_VAULT = Join-Path $env:USERPROFILE "Documents\Sporepath Vault"
$env:SPOREPATH_GRAPH = "real_graph.html"
$env:SPOREPATH_ARCRIFT_URL = "http://127.0.0.1:3001"

$managedProcesses = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Start-ManagedBatch {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Title,
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $process = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/c", "`"$Path`"") `
        -WindowStyle Hidden `
        -PassThru
    $managedProcesses.Add($process)
    return $process
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int] $ProcessId
    )

    taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

try {
    $sourcesWatcher = Start-ManagedBatch -Title "Sporepath Sources Watcher" -Path "$PSScriptRoot\Run-Sporepath-Sources-Watcher.bat"
    $queueWorker = Start-ManagedBatch -Title "Sporepath Queue Worker" -Path "$PSScriptRoot\Run-Sporepath-Queue-Worker.bat"
    $env:SPOREPATH_SOURCES_WATCHER_PID = [string]$sourcesWatcher.Id
    $env:SPOREPATH_QUEUE_WORKER_PID = [string]$queueWorker.Id

    & python -m sporepath --db $env:SPOREPATH_DB app
    $exitCode = $LASTEXITCODE
} finally {
    foreach ($process in $managedProcesses) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-ProcessTree -ProcessId $process.Id
        }
    }
}

exit $exitCode
