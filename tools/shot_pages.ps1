# Launch GameBoostNext and capture one window shot per page.
#
# ============================================================================
# THIS FILE MUST STAY PURE ASCII -- including comments.
# Windows PowerShell 5.1 reads a .ps1 with no BOM as ANSI/GBK, so non-ASCII
# bytes get mis-decoded and can silently swallow the following code line.
# Symptom seen here: a Chinese comment above an `if` block made the whole
# block vanish, so the page filter silently did nothing. Same root cause as
# the earlier Chinese-path mangling.
# Project paths are derived from $PSScriptRoot instead of being hardcoded.
# ============================================================================
#
# Window matching notes (learned the hard way):
#   * Process.MainWindowHandle is unreliable for pywebview/WinForms windows
#   * matching by title alone picks up Explorer windows on paths containing
#     "GameBoostNext", and the owning pid is NOT the one Start-Process returns
#   => match on the window CLASS prefix "WindowsForms10" plus the title
param(
  [string]$OutDir = "",
  [int]$Wait = 6,
  [string]$Theme = "",
  [string]$Only = "",
  [string]$Prefix = "11-M3",
  [string]$Click = "",
  [string]$Page = "",
  [string]$Scroll = "",
  [string]$Eval = ""
)

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
      string s = t.ToString();
      if (s.Length > 0 && s.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) {
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
[void][WinCap]::SetProcessDPIAware()

$next   = Split-Path $PSScriptRoot -Parent
$venvpy = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "venv\Scripts\python.exe"
if (-not $OutDir) { $OutDir = Join-Path $next "design\shots" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$pages = @(
  @{ key = 'overview'; file = "$Prefix-01-overview.png" },
  @{ key = 'memory';   file = "$Prefix-02-memory.png"   },
  @{ key = 'junk';     file = "$Prefix-03-junk.png"     },
  @{ key = 'tools';    file = "$Prefix-04-tools.png"    },
  @{ key = 'settings'; file = "$Prefix-05-settings.png" }
)

# -Page overrides -Only and lets the caller name the output file, which is
# how the "after clicking something" shots are produced.
if ($Page) {
  $pages = @(@{ key = $Page; file = "$Prefix-$Page.png" })
}
elseif ($Only) {
  $filtered = New-Object System.Collections.ArrayList
  foreach ($pg in $pages) {
    if ([string]$pg['key'] -eq [string]$Only) { [void]$filtered.Add($pg) }
  }
  if ($filtered.Count -eq 0) {
    Write-Host "no page named '$Only'"
    exit 1
  }
  $pages = $filtered.ToArray()
  if ($Theme) { $pages[0]['file'] = "$Prefix-06-$Theme-$Only.png" }
}
Write-Host "pages=$($pages.Count) only='$Only' theme='$Theme'"

function Kill-App {
  Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "D:\GameBoostNext\venv\*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force }
}

# Start-Process -ArgumentList does NOT quote elements for you: an argument
# containing spaces gets split into several argv entries. That silently broke
# --eval (its JS is full of spaces) -- the app received only "var".
# Quote anything containing whitespace or quotes.
function Q([string]$s) {
  if ($s -match '[\s"]') { return '"' + ($s -replace '"', '\"') + '"' }
  return $s
}

foreach ($pg in $pages) {
  Kill-App
  Start-Sleep -Milliseconds 500

  $extra = @()
  if ($Theme) { $extra = @("--theme", $Theme) }
  if ($Click) { $extra = $extra + @("--click", $Click) }
  if ($Scroll) { $extra = $extra + @("--scroll", $Scroll) }
  if ($Eval) { $extra = $extra + @("--eval", $Eval) }
  $argList = @("-m","app.main","--page",$pg['key']) + $extra
  $quoted = ($argList | ForEach-Object { Q $_ }) -join ' '
  $p = Start-Process -FilePath $venvpy -ArgumentList $quoted `
        -WorkingDirectory $next -PassThru
  Write-Host "== $($pg['key']): started pid=$($p.Id)"

  $h = [IntPtr]::Zero
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 600
    $h = [WinCap]::Find("WindowsForms10", "mahiru")
    if ($h -ne [IntPtr]::Zero) { break }
  }
  if ($h -eq [IntPtr]::Zero) { Write-Host "   FAIL: no window"; continue }

  [void][WinCap]::SetForegroundWindow($h)
  Start-Sleep -Seconds $Wait

  $c = [WinCap]::ClientOrigin($h)
  $bmp = New-Object System.Drawing.Bitmap($c[2], $c[3])
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($c[0], $c[1], 0, 0, $bmp.Size)
  $out = Join-Path $OutDir $pg['file']
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "   saved $($pg['file'])  $($c[2])x$($c[3])"
}

Kill-App
Write-Host "done"
