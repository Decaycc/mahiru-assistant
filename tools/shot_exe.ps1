# Capture the packaged EXE's real window (proof that the frozen build renders).
# Strictly ASCII.
param(
  [string]$Exe = "",
  [string]$Out = "",
  [int]$Wait = 6
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class ExeCap {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  public struct RECT { public int L; public int T; public int R; public int B; }
  public struct POINT { public int X; public int Y; }
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
  public static int[] ClientOrigin(IntPtr h) {
    RECT c; GetClientRect(h, out c);
    POINT p; p.X = 0; p.Y = 0;
    ClientToScreen(h, ref p);
    return new int[] { p.X, p.Y, c.R - c.L, c.B - c.T };
  }
}
"@
[void][ExeCap]::SetProcessDPIAware()

$next = Split-Path $PSScriptRoot -Parent
# Auto-detect: the product name may change, so never hardcode the exe name.
if (-not $Exe) {
  $cand = @(Get-ChildItem (Join-Path $next "dist") -Filter *.exe -ErrorAction SilentlyContinue)
  if ($cand.Count -eq 0) { Write-Host "FAIL: no exe in dist\"; exit 1 }
  $Exe = $cand[0].FullName
}
if (-not $Out) { $Out = Join-Path $next "design\shots\15-M7-exe.png" }

Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$next\dist\*" } |
  ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 700

$p = Start-Process -FilePath $Exe -PassThru
Write-Host "started exe pid=$($p.Id)"

$h = [IntPtr]::Zero
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  $h = [ExeCap]::Find("WindowsForms10", "mahiru")
  if ($h -ne [IntPtr]::Zero) { break }
}
if ($h -eq [IntPtr]::Zero) {
  Write-Host "FAIL: window not found"
  Stop-Process -Id $p.Id -Force
  exit 1
}

[void][ExeCap]::SetForegroundWindow($h)
Start-Sleep -Seconds $Wait

$c = [ExeCap]::ClientOrigin($h)
$bmp = New-Object System.Drawing.Bitmap($c[2], $c[3])
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($c[0], $c[1], 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host "saved $Out  $($c[2])x$($c[3])"

Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$next\dist\*" } |
  ForEach-Object { Stop-Process -Id $_.Id -Force }
Write-Host "done"
