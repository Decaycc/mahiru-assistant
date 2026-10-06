# Measure GameBoostNext cold-start time: from process start until its window
# is actually on screen (not just "process exists").
# Strictly ASCII. Window matching: class prefix "WindowsForms10" + title.
param(
  [string]$Exe = "",
  [int]$Runs = 3
)

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class StartProbe {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public static IntPtr Find(string classPrefix, string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      StringBuilder c = new StringBuilder(256);
      GetClassName(h, c, c.Capacity);
      if (!c.ToString().StartsWith(classPrefix, StringComparison.Ordinal)) return true;
      StringBuilder t = new StringBuilder(512);
      GetWindowText(h, t, t.Capacity);
      if (t.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) {
        found = h; return false;
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
[void][StartProbe]::SetProcessDPIAware()

$next = Split-Path $PSScriptRoot -Parent
# Auto-detect: the product name may change, so never hardcode the exe name.
if (-not $Exe) {
  $cand = @(Get-ChildItem (Join-Path $next "dist") -Filter *.exe -ErrorAction SilentlyContinue)
  if ($cand.Count -eq 0) { Write-Host "FAIL: no exe in dist\"; exit 1 }
  $Exe = $cand[0].FullName
}
if (-not (Test-Path $Exe)) { Write-Host "FAIL: exe not found: $Exe"; exit 1 }

Write-Host "exe: $Exe"
Write-Host ("size: {0:N2} MB" -f ((Get-Item $Exe).Length / 1MB))
Write-Host ""

$times = @()
for ($i = 1; $i -le $Runs; $i++) {
  Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$next\dist\*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force }
  Start-Sleep -Milliseconds 800

  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process -FilePath $Exe -PassThru

  $h = [IntPtr]::Zero
  while ($sw.Elapsed.TotalSeconds -lt 60) {
    $h = [StartProbe]::Find("WindowsForms10", "mahiru")
    if ($h -ne [IntPtr]::Zero) { break }
    Start-Sleep -Milliseconds 50
  }
  $sw.Stop()

  if ($h -eq [IntPtr]::Zero) {
    Write-Host ("run {0}: FAIL - window never appeared" -f $i)
  } else {
    $t = $sw.Elapsed.TotalSeconds
    $times += $t
    Write-Host ("run {0}: window visible after {1:N2}s" -f $i, $t)
  }
  Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$next\dist\*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force }
  Start-Sleep -Milliseconds 400
}

if ($times.Count) {
  $avg = ($times | Measure-Object -Average).Average
  $max = ($times | Measure-Object -Maximum).Maximum
  Write-Host ""
  Write-Host ("average {0:N2}s   worst {1:N2}s   (target < 4s)" -f $avg, $max)
}
