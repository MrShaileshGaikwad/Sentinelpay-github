$ErrorActionPreference = "Stop"
$debounceSeconds = 5
$pushRetrySeconds = 30
$lastPushAttempt = [DateTime]::MinValue
$lastStatus = $null
$lastChange = [DateTime]::UtcNow

$repositoryRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repositoryRoot) {
    throw "Auto-sync must run inside a Git repository."
}
Set-Location $repositoryRoot.Trim()

function Get-RepositoryStatus {
    $result = & git status --porcelain --untracked-files=all 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read Git status: $($result -join ' ')"
    }
    return ($result -join "`n")
}

function Invoke-GitChecked {
    param([string[]]$GitArguments)
    $result = & git @GitArguments 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in $result) {
        Write-Host $line
    }
    if ($exitCode -ne 0) {
        throw "git $($GitArguments -join ' ') failed with exit code $exitCode."
    }
}

function Test-BlockedPath {
    param([string]$Path)
    $normalized = $Path.Replace("\", "/")
    $name = [System.IO.Path]::GetFileName($normalized)
    if ($name -match '^(?i:\.env)(?!\.example$)' -or
        $name -match '(?i)(^|[._-])(secret|credentials?|passwords?|tokens?)([._-]|$)' -or
        $name -match '(?i)(api|private)[_-]?key' -or
        $name -match '^(?i:id_(rsa|ed25519))$' -or
        $name -match '(?i)\.(pem|p12|pfx|key|sqlite3?|db)$') {
        return $true
    }
    return $false
}

function Push-LocalCommits {
    if (([DateTime]::UtcNow - $script:lastPushAttempt).TotalSeconds -lt $pushRetrySeconds) {
        return
    }
    $script:lastPushAttempt = [DateTime]::UtcNow

    $upstream = & git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $upstream) {
        Write-Warning "No upstream is configured; set one before auto-sync can push."
        return
    }

    $counts = (& git rev-list --left-right --count "HEAD...$($upstream.Trim())" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not compare the current branch with its upstream: $($counts -join ' ')"
    }
    $aheadBehind = ($counts -join " ").Trim() -split '\s+'
    $ahead = [int]$aheadBehind[0]
    $behind = [int]$aheadBehind[1]
    if ($behind -gt 0) {
        Write-Warning "The upstream has $behind newer commit(s). Auto-sync will not rebase or push until you sync the branch."
        return
    }
    if ($ahead -gt 0) {
        Invoke-GitChecked -GitArguments @("push")
        Write-Host "Auto-sync: pushed $ahead local commit(s) to $($upstream.Trim())."
    }
}

Write-Host "Auto-sync is watching $repositoryRoot"
Write-Host "Saved changes are committed after $debounceSeconds seconds of inactivity and then pushed to the current upstream."
Write-Host "Stop this task with Ctrl+C. Secret files and local database files are never auto-committed."

while ($true) {
    try {
        $status = Get-RepositoryStatus
        if ($status -ne $lastStatus) {
            $lastStatus = $status
            $lastChange = [DateTime]::UtcNow
            if ($status) {
                Write-Host "Auto-sync: detected saved or staged changes; waiting for edits to settle."
            }
        }

        if ($status -and ([DateTime]::UtcNow - $lastChange).TotalSeconds -ge $debounceSeconds) {
            $branch = & git symbolic-ref --quiet --short HEAD 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $branch) {
                Write-Warning "Detached HEAD detected. Auto-sync will not create a commit until a branch is checked out."
                $lastChange = [DateTime]::UtcNow
            }
            else {
                $protected = @(& git diff --name-only --cached; & git ls-files --others --exclude-standard)
                $protected += @(& git diff --name-only)
                $blocked = @($protected | Where-Object { $_ -and (Test-BlockedPath $_) } | Sort-Object -Unique)
                if ($blocked.Count -gt 0) {
                    Write-Warning "Auto-sync paused. Review these protected files and remove them from the index before continuing:"
                    foreach ($path in $blocked) {
                        Write-Warning "  $path"
                    }
                    $lastChange = [DateTime]::UtcNow
                }
                else {
                    Invoke-GitChecked -GitArguments @("add", "-A")
                    $staged = & git diff --cached --quiet
                    $diffExitCode = $LASTEXITCODE
                    if ($diffExitCode -eq 1) {
                        $commitMessage = "Auto-sync saved workspace changes"
                        Invoke-GitChecked -GitArguments @(
                            "commit",
                            "-m", $commitMessage,
                            "-m", "Automatically committed after saved workspace changes.",
                            "-m", "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
                        )
                        Write-Host "Auto-sync: committed saved changes on $($branch.Trim())."
                    }
                    elseif ($diffExitCode -ne 0) {
                        throw "Could not inspect staged changes."
                    }
                    $lastStatus = Get-RepositoryStatus
                    $lastChange = [DateTime]::UtcNow
                    Push-LocalCommits
                }
            }
        }

        if (([DateTime]::UtcNow - $lastPushAttempt).TotalSeconds -ge $pushRetrySeconds) {
            Push-LocalCommits
        }
    }
    catch {
        Write-Warning "Auto-sync could not finish: $($_.Exception.Message)"
        Write-Warning "Local changes and commits are preserved. The watcher will retry automatically when it can."
        $lastChange = [DateTime]::UtcNow
        $lastPushAttempt = [DateTime]::UtcNow
    }
    Start-Sleep -Seconds 2
}
