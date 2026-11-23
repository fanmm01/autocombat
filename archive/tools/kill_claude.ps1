<#
.SYNOPSIS
    Force-stop Claude Code CLI and Claude desktop processes, then verify none remain.

.DESCRIPTION
    Stops every Claude.exe process (including the Claude desktop app and its helpers),
    plus Node.js processes launched from the official Claude Code package/install paths.
    It sweeps repeatedly because a VS Code extension or another supervisor may restart
    Claude Code.

    Exit codes: 0 = clean, 1 = matching processes are still alive.

.PARAMETER ListOnly
    Only list matching processes. Nothing is stopped.

.PARAMETER DryRun
    Show what would be killed without killing anything.

.PARAMETER Watch
    Keep sweeping every IntervalSeconds until Ctrl+C.

.PARAMETER IntervalSeconds
    Watch-mode sweep interval (default 10).

.PARAMETER MaxPasses
    Maximum kill passes per sweep (default 5).

.PARAMETER SettleSeconds
    Wait between passes and before the final check (default 2).
#>
[CmdletBinding()]
param(
    [switch]$ListOnly,
    [switch]$DryRun,
    [switch]$Watch,
    [ValidateRange(1, 3600)][int]$IntervalSeconds = 10,
    [ValidateRange(1, 50)][int]$MaxPasses = 5,
    [ValidateRange(0, 30)][int]$SettleSeconds = 2
)

$ErrorActionPreference = 'Continue'
$script:TotalKilled = 0

function Get-ClaudeProcesses {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    foreach ($process in $processes) {
        $name = [string]$process.Name
        $commandLine = [string]$process.CommandLine

        # Claude.exe is used by both the CLI and desktop app, including Electron helpers.
        if ($name -match '^(?i:claude)(\.exe)?$') {
            $process
            continue
        }

        # Match generic Node hosts only when their command line identifies Claude Code.
        if ($name -match '^(?i:node|node_repl)(\.exe)?$' -and $commandLine -match '(?i)(@anthropic-ai[\\/]claude-code|[\\/]claude-code[\\/]|[\\/]\.local[\\/](bin[\\/]claude|share[\\/]claude)(?:[\\/]|\s|$))') {
            $process
        }
    }
}

function Format-ClaudeProcess {
    param($Process)
    $exe = $Process.ExecutablePath
    if (-not $exe) { $exe = '<path unavailable>' }
    '  {0,-24} PID {1,-6} parent {2,-6} {3}' -f $Process.Name, $Process.ProcessId, $Process.ParentProcessId, $exe
}

function Show-ClaudeProcesses {
    $processes = @(Get-ClaudeProcesses | Sort-Object Name, ProcessId)
    if ($processes.Count -eq 0) {
        Write-Host 'No Claude Code or Claude desktop processes running.'
        return
    }
    Write-Host ("{0} matching process(es) running:" -f $processes.Count)
    foreach ($process in $processes) { Write-Host (Format-ClaudeProcess $process) }
}

function Invoke-ClaudeSweep {
    for ($pass = 1; $pass -le $MaxPasses; $pass++) {
        $processes = @(Get-ClaudeProcesses | Sort-Object Name, ProcessId)
        if ($processes.Count -eq 0) { break }

        Write-Host ("Pass {0}/{1}: terminating {2} process(es)" -f $pass, $MaxPasses, $processes.Count)
        foreach ($process in $processes) {
            $label = '{0} (PID {1})' -f $process.Name, $process.ProcessId
            if ($DryRun) {
                Write-Host "  [dry-run] would kill $label"
                continue
            }

            & taskkill.exe /PID $process.ProcessId /T /F *> $null
            $stillAlive = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ProcessId)" -ErrorAction SilentlyContinue
            if ($stillAlive) {
                Write-Host "  [fail] $label (still running - access denied?)"
            } else {
                Write-Host "  [ok]   $label"
                $script:TotalKilled++
            }
        }

        if ($DryRun) { break }
        if ($SettleSeconds -gt 0) { Start-Sleep -Seconds $SettleSeconds }
    }
}

Write-Host '=== Claude Code and desktop process cleanup ==='
Write-Host ("Time: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host ''

if ($ListOnly) {
    Show-ClaudeProcesses
    exit 0
}

if ($Watch) {
    Write-Host ("Watch mode: sweeping every {0}s. Press Ctrl+C to stop." -f $IntervalSeconds)
    while ($true) {
        $before = $script:TotalKilled
        Invoke-ClaudeSweep
        $remaining = @(Get-ClaudeProcesses)
        if ($script:TotalKilled -gt $before) {
            Write-Host ("Terminated {0} process(es); {1} still running." -f ($script:TotalKilled - $before), $remaining.Count)
        }
        if ($remaining.Count -gt 0) {
            Write-Host ("{0} matching process(es) remain; retrying in {1}s." -f $remaining.Count, $IntervalSeconds)
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Invoke-ClaudeSweep
if ($DryRun) {
    Write-Host ''
    Write-Host 'Dry run complete. No processes were terminated.'
    exit 0
}
if ($SettleSeconds -gt 0) { Start-Sleep -Seconds $SettleSeconds }

$remaining = @(Get-ClaudeProcesses)
Write-Host ''
if ($remaining.Count -eq 0) {
    if ($DryRun) {
        Write-Host 'Dry run complete. No processes were terminated.'
    } else {
        Write-Host ("Clean. {0} process(es) terminated; no matching process is running." -f $script:TotalKilled)
    }
    exit 0
}

Write-Warning ("{0} matching process(es) are still alive:" -f $remaining.Count)
foreach ($process in $remaining) { Write-Host (Format-ClaudeProcess $process) }
Write-Host 'A VS Code extension or another supervisor may be restarting Claude Code.'
Write-Host 'Close the Claude Code panel or use -Watch to keep sweeping.'
exit 1
