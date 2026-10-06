# Diagnostic: start the app, then list every visible top-level window whose
# title contains "GameBoost" or whose owning process is python-like, with PIDs.
# ASCII only.
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WEnum {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);

  public static List<string> All() {
    List<string> rows = new List<string>();
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      int pid;
      GetWindowThreadProcessId(h, out pid);
      StringBuilder t = new StringBuilder(512);
      GetWindowText(h, t, t.Capacity);
      StringBuilder c = new StringBuilder(256);
      GetClassName(h, c, c.Capacity);
      string title = t.ToString();
      if (title.Length == 0) return true;
      rows.Add(pid + "\t" + c.ToString() + "\t" + title);
      return true;
    }, IntPtr.Zero);
    return rows;
  }
}
"@
[void][WEnum]::SetProcessDPIAware()

$next   = Split-Path $PSScriptRoot -Parent
$venvpy = "D:\GameBoostNext\venv\Scripts\python.exe"

$p = Start-Process -FilePath $venvpy -ArgumentList "-m","app.main" `
                   -WorkingDirectory $next -PassThru
Write-Host "launched pid=$($p.Id)"
Start-Sleep -Seconds 8
$p.Refresh()
Write-Host "hasExited=$($p.HasExited)"

Write-Host ""
Write-Host "--- all python-ish processes ---"
$pyPids = @()
Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -match 'python|msedgewebview' } |
  ForEach-Object {
    $pyPids += $_.Id
    Write-Host ("  pid={0,-8} {1,-22} hwnd={2}" -f $_.Id, $_.ProcessName, $_.MainWindowHandle)
  }

Write-Host ""
Write-Host "--- visible windows with title containing mahiru ---"
foreach ($row in [WEnum]::All()) {
  $parts = $row -split "`t"
  if ($parts[2] -match 'mahiru') {
    Write-Host "  pid=$($parts[0])  class=$($parts[1])  title=$($parts[2])"
  }
}

Write-Host ""
Write-Host "--- visible windows owned by python pids ---"
foreach ($row in [WEnum]::All()) {
  $parts = $row -split "`t"
  if ($pyPids -contains [int]$parts[0]) {
    Write-Host "  pid=$($parts[0])  class=$($parts[1])  title=$($parts[2])"
  }
}

if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Get-Process -Name python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like "D:\GameBoostNext\venv\*" } |
  ForEach-Object { Stop-Process -Id $_.Id -Force }
Write-Host ""
Write-Host "done"
