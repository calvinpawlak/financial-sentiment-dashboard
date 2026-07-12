<#
Sets up TWO Windows Task Scheduler tasks so the Financial Sentiment
Dashboard's ingestion layer keeps refreshing without you having to run it
by hand:

  - A "fast" task every 5 minutes: prices, StockTwits, Reddit, Finnhub.
  - A "slow" task every 15 minutes: FinViz + Google News.

Split 2026-07-12: FinViz only updates news ~every 30 min and its terms
discourage high-frequency automated hits; Google News RSS is unofficial
with no documented rate limit either. Polling either one every 5 min would
just refetch the same headlines 3x as often for no new data, while raising
scraping-detection risk for no benefit. The other sources all comfortably
support 5 minutes. See main.py --fast-only / --slow-only.

USAGE (run once, from inside this project folder):
    powershell -ExecutionPolicy Bypass -File .\setup_task_scheduler.ps1

If you get an "Access Denied" error, right-click PowerShell and choose
"Run as Administrator", then run the command again.

Safe to re-run - it replaces any existing tasks with the same names, so you
can use it again later if you want to change the intervals (edit
$FastRepetitionMinutes / $SlowRepetitionMinutes below) or move the project
folder.
#>

$FastTaskName = "FinancialSentimentDashboard-Ingestion-Fast"
$SlowTaskName = "FinancialSentimentDashboard-Ingestion-Slow"
$FastRepetitionMinutes = 5
$SlowRepetitionMinutes = 15
$ProjectDir = $PSScriptRoot
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source

if (-not $PythonPath) {
    Write-Host "Could not find python.exe on PATH." -ForegroundColor Red
    Write-Host "If you're using a virtual environment, activate it first and re-run this script." -ForegroundColor Red
    Write-Host "Otherwise, edit this script and hardcode `$PythonPath to the full path to python.exe." -ForegroundColor Red
    exit 1
}

Write-Host "Project folder: $ProjectDir"
Write-Host "Python path:     $PythonPath"
Write-Host "Fast interval:   every $FastRepetitionMinutes minutes (prices, StockTwits, Reddit, Finnhub)"
Write-Host "Slow interval:   every $SlowRepetitionMinutes minutes (FinViz, Google News)"

$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

function Register-IngestionTask {
    param(
        [string]$TaskName,
        [string]$Argument,
        [int]$RepetitionMinutes,
        [string]$Description
    )

    $Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $Argument -WorkingDirectory $ProjectDir

    # Fire once shortly after creation, then repeat on the configured
    # interval for (effectively) forever - Task Scheduler's cmdlets don't
    # have a true "indefinite" duration, so 10 years is the standard
    # workaround.
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $RepetitionMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)

    # Remove any existing task with the same name so this script is safe to re-run.
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
        -Description $Description | Out-Null
}

Register-IngestionTask -TaskName $FastTaskName -Argument "main.py --fast-only" `
    -RepetitionMinutes $FastRepetitionMinutes `
    -Description "Runs prices, StockTwits, Reddit, and Finnhub ingestion every $FastRepetitionMinutes minutes."

Register-IngestionTask -TaskName $SlowTaskName -Argument "main.py --slow-only" `
    -RepetitionMinutes $SlowRepetitionMinutes `
    -Description "Runs FinViz and Google News ingestion every $SlowRepetitionMinutes minutes."

Write-Host ""
Write-Host "Tasks created:" -ForegroundColor Green
Write-Host "  '$FastTaskName' - starts within 1 minute, repeats every $FastRepetitionMinutes minutes" -ForegroundColor Green
Write-Host "  '$SlowTaskName' - starts within 1 minute, repeats every $SlowRepetitionMinutes minutes" -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Check status:  Get-ScheduledTask -TaskName '$FastTaskName' | Get-ScheduledTaskInfo"
Write-Host "  Run right now: Start-ScheduledTask -TaskName '$FastTaskName'"
Write-Host "  Remove both:   Unregister-ScheduledTask -TaskName '$FastTaskName'; Unregister-ScheduledTask -TaskName '$SlowTaskName'"
Write-Host "  View logs:     Get-Content .\logs\ingestion.log -Tail 30 -Wait"
Write-Host ""
Write-Host "If you previously ran the old single-task version of this script, remove it manually:" -ForegroundColor Yellow
Write-Host "  Unregister-ScheduledTask -TaskName 'FinancialSentimentDashboard-Ingestion' -ErrorAction SilentlyContinue" -ForegroundColor Yellow
