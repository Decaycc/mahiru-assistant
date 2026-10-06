# Launch GameBoostNext, capture its real window, then close it.
# Keep this file strictly ASCII: non-ASCII literals get mangled when the file
# is read under a non-UTF8 console codepage. Paths come from $PSScriptRoot.
#
# Note: Process.MainWindowHandle is unreliable for pywebview/WinForms windows
# (it was unreliable for the earlier tkinter build too), so enumerate top-level
# windows and match the title instead.
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinCap {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public struct POINT { public int X; public int Y; }

  // Match by WINDOW CLASS prefix, not by pid.
  // Two traps found the hard way:
  //  1. title alone picks up an Explorer window on a path containing "GameBoost"
  //  2. the owning pid is NOT the pid Start-Process returns -- the venv's
  //     python.exe re-launches another python that actually owns the window
  // The pywebview/WinForms window class starts with "WindowsForms10", which
  // cleanly excludes Explorer and terminal windows.
  public static IntPtr Find(string classPrefix, string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      StringBuilder c = new StringBuilder(256);
      GetClassName(h, c, c.Capacity);
      if (!c.ToString().StartsWith(classPrefix, StringComparison.Ordinal)) return true;
      StringBuilder sb = new StringBuilder(512);
      GetWindowText(h, sb, sb.Capacity);
      string t = sb.ToString();
      if (t.Length > 0 && t.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) {
        found = h;
        return false;
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }

  public static int[] ClientOrigin(IntPtr h) {
    RECT c;
    GetClientRect(h, out c);
    POINT p;
    p.X = 0; p.Y = 0;
    ClientToScreen(h, ref p);
    return new int[] { p.X, p.Y, c.R - c.L, c.B - c.T };
  }
}
"@
[void][WinCap]::SetProcessDPIAware()

$next   = Split-Path $PSScriptRoot -Parent
$venvpy = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "venv\Scripts\python.exe"
$out    = Join-Path $next "design\shots\10-M2-window.png"
$applog = Join-Path $next "config\_shot_app.log"

New-Item -ItemType Directory -Force -Path (Split-Path $applog) | Out-Null
Remove-Item $applog -ErrorAction SilentlyContinue

$p = Start-Process -FilePath $venvpy -ArgumentList "-m","app.main" `
                   -WorkingDirectory $next -PassThru `
                   -RedirectStandardOutput $applog -RedirectStandardError "$applog.err"
Write-Host "started pid=$($p.Id), waiting for window..."

$h = [IntPtr]::Zero
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 700
  $h = [WinCap]::Find("WindowsForms10", "mahiru")
  if ($h -ne [IntPtr]::Zero) { Write-Host "window found after $([math]::Round(($i+1)*0.7,1))s"; break }
}

if ($h -eq [IntPtr]::Zero) {
  Write-Host "FAIL: no mahiru WinForms window found"
  Write-Host "--- app stdout ---"; Get-Content $applog -ErrorAction SilentlyContinue | Select-Object -First 30
  Write-Host "--- app stderr ---"; Get-Content "$applog.err" -ErrorAction SilentlyContinue | Select-Object -First 30
  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
  exit 1
}

[void][WinCap]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 1100

# Capture the CLIENT area (excludes the title bar and borders)
$c = [WinCap]::ClientOrigin($h)
$cx = $c[0]; $cy = $c[1]; $w = $c[2]; $ht = $c[3]
Write-Host "client area: $cx,$cy size ${w}x${ht}"

$bmp = New-Object System.Drawing.Bitmap($w, $ht)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($cx, $cy, 0, 0, $bmp.Size)
$bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
Write-Host "saved $out"

if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Start-Sleep -Milliseconds 600
Get-Process -Name python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like "D:\GameBoostNext\venv\*" } |
  ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Host "cleaned pid $($_.Id)" }
Write-Host "done"
