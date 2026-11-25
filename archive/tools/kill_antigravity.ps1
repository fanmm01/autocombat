<#
.SYNOPSIS
    Force-stop every Google Antigravity IDE and CLI (agy.exe) process on this machine,
    then verify none remain.

.DESCRIPTION
    Antigravity is an Electron/VS Code-based IDE, so it runs as a tree of processes:
      * Antigravity.exe                - main window, renderer, GPU, utility and crashpad processes
      * Antigravity Helper.exe         - Electron helper processes on some builds
      * agy.exe                        - Antigravity CLI/hub, normally installed as
                                         %USERPROFILE%\.gemini\bin\agy.exe
      * node.exe / language servers    - generic runtimes started from the Antigravity install
                                         folder, its user-data folder (%APPDATA%\Antigravity)
                                         or a .antigravity config/cache folder

    Processes are matched by executable name, executable path and command line, so helpers
    with generic names are included. Process-tree roots are stopped first; stopping the
    root usually makes the Electron helpers exit instead of being respawned. The sweep is
    repeated (MaxPasses) and verified after a settle delay.

    The script refuses to kill anything when its own console is running inside Antigravity
    (for example the IDE's integrated terminal), because stopping the IDE would terminate
    the cleanup halfway through. Run the .bat from Explorer or another terminal instead.

    Exit codes: 0 = clean, 1 = processes are still alive or the cleanup was refused.

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

.EXAMPLE
    .\kill_antigravity.ps1

.EXAMPLE
    .\kill_antigravity.ps1 -ListOnly

.EXAMPLE
    .\kill_antigravity.ps1 -Watch -IntervalSeconds 5
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

# Matches Antigravity install paths, user-data dirs and executables in an executable
# path or command line. The leading separator keeps kill_antigravity.ps1/.bat from
# matching themselves (the underscore is not a path separator).
$PathPattern = '(?i)([\\/]\.?antigravity([\\/]|["''\s]|$)|\bantigravity\.exe\b)'

# The Antigravity CLI/hub is agy.exe under the shared Gemini home, e.g.
# %USERPROFILE%\.gemini\bin\agy.exe. Match that name and install path only, so
# Gemini CLI processes (gemini.exe, node.exe, ...) are left alone.
$CliPathPattern = '(?i)([\\/]\.gemini[\\/]bin[\\/]agy(\.exe)?(["''\s]|$))'

function Test-AntigravityProcess {
    param($Process)
    $name = [string]$Process.Name
    if (-not $name) { return $false }

    # Antigravity.exe, Antigravity Helper.exe, AntigravityUpdate.exe, ...
    if ($name -match '^antigravity') { return $true }

    # agy.exe (Antigravity CLI/hub) and versioned or helper builds such as agy-0.1.0.exe
    if ($name -match '^agy([-_.].*)?$') { return $true }

    $exe = [string]$Process.ExecutablePath
    if ($exe -and ($exe -match $PathPattern -or $exe -match $CliPathPattern)) { return $true }

    $cmd = [string]$Process.CommandLine
    if ($cmd -and ($cmd -match $PathPattern -or $cmd -match $CliPathPattern)) { return $true }

    return $false
}

function Get-ProtectedIds {
    # This process and all of its ancestors: never kill the shell running the cleanup.
    param($Processes)
    $parentOf = @{}
    foreach ($process in $Processes) {
        $parentOf[[int]$process.ProcessId] = [int]$process.ParentProcessId
    }

    $protected = @{}
    $current = [int]$PID
    while ($current -and -not $protected.ContainsKey($current)) {
        $protected[$current] = $true
        if (-not $parentOf.ContainsKey($current)) { break }
        $current = $parentOf[$current]
    }
    return ,$protected
}

function Test-InsideAntigravity {
    param($Processes)
    $byId = @{}
    foreach ($process in $Processes) { $byId[[int]$process.ProcessId] = $process }

    $seen = @{}
    $current = [int]$PID
    while ($current -and -not $seen.ContainsKey($current)) {
        $seen[$current] = $true
        if (-not $byId.ContainsKey($current)) { break }
        $current = [int]$byId[$current].ParentProcessId
        if ($current -and $byId.ContainsKey($current) -and (Test-AntigravityProcess $byId[$current])) {
            return $true
        }
    }
    return $false
}

function Get-AntigravityProcesses {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $protected = Get-ProtectedIds $processes
    foreach ($process in $processes) {
        if ($protected.ContainsKey([int]$process.ProcessId)) { continue }
        if (Test-AntigravityProcess $process) { $process }
    }
}

function Format-AntigravityProcess {
    param($Process)
    $exe = $Process.ExecutablePath
    if (-not $exe) { $exe = '<path unavailable>' }
    '  {0,-28} PID {1,-6} parent {2,-6} {3}' -f $Process.Name, $Process.ProcessId, $Process.ParentProcessId, $exe
}

function Show-AntigravityProcesses {
    $processes = @(Get-AntigravityProcesses | Sort-Object Name, ProcessId)
    if ($processes.Count -eq 0) {
        Write-Host 'No Antigravity processes running.'
        return
    }
    Write-Host ("{0} Antigravity process(es) running:" -f $processes.Count)
    foreach ($process in $processes) { Write-Host (Format-AntigravityProcess $process) }
}

function Invoke-AntigravitySweep {
    for ($pass = 1; $pass -le $MaxPasses; $pass++) {
        $processes = @(Get-AntigravityProcesses)
        if ($processes.Count -eq 0) { break }

        $ids = @{}
        foreach ($process in $processes) { $ids[[int]$process.ProcessId] = $true }

        # Roots first: killing the main Electron process makes its helpers exit
        # instead of leaving them behind to be respawned.
        $roots = @($processes | Where-Object { -not $ids.ContainsKey([int]$_.ParentProcessId) })
        $children = @($processes | Where-Object { $ids.ContainsKey([int]$_.ParentProcessId) })
        $ordered = @($roots) + @($children)

        Write-Host ("Pass {0}/{1}: terminating {2} process(es)" -f $pass, $MaxPasses, $processes.Count)

        foreach ($process in $ordered) {
            $label = '{0} (PID {1})' -f $process.Name, $process.ProcessId

            if ($DryRun) {
                Write-Host "  [dry-run] would kill $label"
                continue
            }

            & taskkill.exe /PID $process.ProcessId /T /F *> $null

            # /T already reaped most children, so a non-zero exit code is normal.
            # Judge by whether the process is actually gone, not by taskkill's code.
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

Write-Host '=== Antigravity process cleanup ==='
Write-Host ("Time: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host ''

if ($ListOnly) {
    Show-AntigravityProcesses
    exit 0
}

if (-not $DryRun) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    if (Test-InsideAntigravity $all) {
        Write-Warning 'This console is running inside Antigravity.'
        Write-Host 'Killing the IDE from its own integrated terminal would stop this cleanup halfway through.'
        Write-Host 'Run kill_antigravity.bat from Explorer, Windows Terminal, or another shell outside Antigravity.'
        exit 1
    }
}

if ($Watch) {
    Write-Host ("Watch mode: sweeping every {0}s. Press Ctrl+C to stop." -f $IntervalSeconds)
    while ($true) {
        $before = $script:TotalKilled
        Invoke-AntigravitySweep
        $remaining = @(Get-AntigravityProcesses)
        if ($script:TotalKilled -gt $before) {
            Write-Host ("Terminated {0} process(es); {1} still running." -f ($script:TotalKilled - $before), $remaining.Count)
        }
        if ($remaining.Count -gt 0) {
            Write-Host ("{0} matching process(es) remain; retrying in {1}s." -f $remaining.Count, $IntervalSeconds)
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Invoke-AntigravitySweep
if ($DryRun) {
    Write-Host ''
    Write-Host 'Dry run complete. No processes were terminated.'
    exit 0
}
if ($SettleSeconds -gt 0) { Start-Sleep -Seconds $SettleSeconds }

$remaining = @(Get-AntigravityProcesses)
Write-Host ''
if ($remaining.Count -eq 0) {
    Write-Host ("Clean. {0} process(es) terminated; no Antigravity process is running." -f $script:TotalKilled)
    exit 0
}

Write-Warning ("{0} Antigravity process(es) are still alive:" -f $remaining.Count)
foreach ($process in $remaining) { Write-Host (Format-AntigravityProcess $process) }
Write-Host ''
Write-Host 'The Antigravity VS Code extension, an updater or another session may be restarting it.'
Write-Host 'Close the Antigravity window (or the app that launched it), then run again.'
Write-Host 'Use -Watch to keep sweeping while it is closed.'
exit 1
