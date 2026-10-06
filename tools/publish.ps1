# Wait for gh auth, then create the repo and push.
# STRICTLY ASCII: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# and non-ASCII bytes silently corrupt parsing (hit this before).
$ErrorActionPreference = 'Continue'
$gh   = "C:\Program Files\GitHub CLI\gh.exe"
# Derive the repo path from this script's location -- the real path contains
# non-ASCII characters (user name), which would make this file non-ASCII too.
$repo = Split-Path $PSScriptRoot -Parent
$name = "mahiru-assistant"
$log  = "$env:TEMP\mahiru_publish.log"

function Say($m) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
  Write-Host $line
  Add-Content -Path $log -Value $line -Encoding UTF8
}

Set-Content -Path $log -Value "mahiru publish log" -Encoding UTF8

# ---- 1. wait for authorization (up to 15 min)
Say "waiting for GitHub authorization..."
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
  Start-Sleep -Seconds 5
  $s = & $gh auth status 2>&1 | Out-String
  if ($s -match 'Logged in to github\.com') { $ok = $true; break }
}
if (-not $ok) {
  Say "FAIL: no authorization within 15 minutes"
  exit 1
}
Say "authorized"

# ---- 2. who am i
$user = (& $gh api user --jq .login 2>&1 | Out-String).Trim()
if (-not $user -or $user -match 'error|not found') {
  Say "FAIL: cannot get username: $user"
  exit 1
}
Say "user: $user"

# ---- 3. create repo (private by default; flip to public on the web anytime)
& $gh repo view "$user/$name" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Say "repo $user/$name already exists, skipping create"
} else {
  Say "creating repo $user/$name (private)..."
  $desc = "Windows game booster and cleaner: memory optimization, junk cleanup, startup manager, large/duplicate file finder"
  $out = & $gh repo create $name --private --source $repo --remote origin --description $desc 2>&1 | Out-String
  Say $out.Trim()
}

# ---- 4. push
Set-Location $repo
& git remote remove origin 2>&1 | Out-Null
& git remote add origin "https://github.com/$user/$name.git"
& git branch -M main 2>&1 | Out-Null
Say "pushing..."
$push = & git push -u origin main 2>&1 | Out-String
Say $push.Trim()

if ($LASTEXITCODE -eq 0) {
  Say "DONE  https://github.com/$user/$name"
} else {
  Say "FAIL: push exited with $LASTEXITCODE"
}
