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
        -WindowStyle Minimized `
        -PassThru
    $managedProcesses.Add($process)
    Write-Host "Started ${Title}: pid=$($process.Id)"
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int] $ProcessId
    )

    taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

try {
    Start-ManagedBatch -Title "Sporepath Sources Watcher" -Path "$PSScriptRoot\Run-Sporepath-Sources-Watcher.bat"
    Start-ManagedBatch -Title "Sporepath Queue Worker" -Path "$PSScriptRoot\Run-Sporepath-Queue-Worker.bat"

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
