<#
.SYNOPSIS
    Install (or uninstall) the Woodworking AI add-in into Autodesk Fusion 360.

.DESCRIPTION
    Fusion loads add-ins from its per-user Add-Ins folder. This script wires the
    add-in up there so Fusion can find it, then verifies the pure-Python
    `woodworking_ai` package resolves.

    Two install modes:

      * Junction (default) -- creates a directory junction from
        <AddIns>\WoodworkingAI to the repo's `fusion360` folder. Because
        os.path.realpath() follows the junction back to the real repo path, the
        add-in's own loader finds `..\src\woodworking_ai` automatically. Edits in
        the repo are picked up on the add-in's next "Run" -- nothing to re-copy.
        No admin rights required (junctions, unlike symlinks, don't need them).

      * Copy (-Copy) -- copies the add-in files into <AddIns>\WoodworkingAI and
        vendors a snapshot of `src\woodworking_ai` beside them. Self-contained
        and repo-independent, but frozen at install time -- re-run to update.

.PARAMETER Source
    The `fusion360` add-in folder to install from. Defaults to the folder this
    script lives in.

.PARAMETER Copy
    Vendor a self-contained copy instead of creating a live junction.

.PARAMETER Uninstall
    Remove the add-in from the Fusion Add-Ins folder (junction or copy).

.PARAMETER Force
    Replace an existing WoodworkingAI install without prompting.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
    # live junction to this repo (recommended for development)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Copy
    # self-contained copy (recommended for a machine without the repo)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string] $Source = $PSScriptRoot,
    [switch] $Copy,
    [switch] $Uninstall,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$AddinName = 'WoodworkingAI'

function Get-FusionAddInsDir {
    # Fusion 360 (per-user) add-ins live here on Windows.
    $dir = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns'
    if (-not (Test-Path $dir)) {
        throw "Fusion Add-Ins folder not found at:`n  $dir`n" +
              "Is Autodesk Fusion 360 installed for this user?"
    }
    return $dir
}

function Resolve-PackageRoot {
    param([string] $InstalledDir)
    # Mirror WoodworkingAI.py::_ensure_woodworking_ai_on_path, which resolves the
    # add-in's REAL location first (os.path.realpath) before walking candidates.
    # We must do the same: for a junction, `..` must be collapsed against the
    # junction's target, not against the Add-Ins folder it lexically sits in.
    $item = Get-Item $InstalledDir -Force
    $base = if ($item.LinkType -eq 'Junction') { $item.Target | Select-Object -First 1 } else { $InstalledDir }
    $candidates = @(
        $base,
        (Join-Path $base 'vendor'),
        (Join-Path $base 'src'),
        (Join-Path $base '..\src')
    )
    foreach ($c in $candidates) {
        $c = [System.IO.Path]::GetFullPath($c)   # collapse `..` on the real path
        if (Test-Path (Join-Path $c 'woodworking_ai\__init__.py')) {
            return $c
        }
    }
    return $null
}

$addins = Get-FusionAddInsDir
$target = Join-Path $addins $AddinName

# --- Uninstall -----------------------------------------------------------
if ($Uninstall) {
    if (-not (Test-Path $target)) {
        Write-Host "Nothing to remove: $target does not exist." -ForegroundColor Yellow
        return
    }
    $item = Get-Item $target -Force
    if ($item.LinkType -eq 'Junction') {
        # Remove the junction only -- never recurse into the repo it points at.
        [System.IO.Directory]::Delete($target)
        Write-Host "Removed junction: $target" -ForegroundColor Green
    } else {
        Remove-Item $target -Recurse -Force
        Write-Host "Removed copy: $target" -ForegroundColor Green
    }
    Write-Host "In Fusion: Utilities -> Add-Ins -> Scripts and Add-Ins, then Stop the add-in if it is still running."
    return
}

# --- Validate source -----------------------------------------------------
$Source = (Resolve-Path $Source).Path
$entry = Join-Path $Source "$AddinName.py"
$manifest = Join-Path $Source "$AddinName.manifest"
if (-not (Test-Path $entry) -or -not (Test-Path $manifest)) {
    throw "Source does not look like the add-in folder (missing $AddinName.py / .manifest):`n  $Source"
}

# --- Handle an existing install ------------------------------------------
if (Test-Path $target) {
    $existing = Get-Item $target -Force
    $kind = if ($existing.LinkType -eq 'Junction') { "junction -> $($existing.Target)" } else { 'copy' }
    if (-not $Force) {
        $ans = Read-Host "An install already exists ($kind).`nReplace it? [y/N]"
        if ($ans -notmatch '^(y|yes)$') { Write-Host 'Aborted.'; return }
    }
    if ($existing.LinkType -eq 'Junction') {
        [System.IO.Directory]::Delete($target)
    } else {
        Remove-Item $target -Recurse -Force
    }
}

# --- Install -------------------------------------------------------------
if ($Copy) {
    New-Item -ItemType Directory -Path $target | Out-Null
    # Add-in files (skip a stray git-ignored key file and any vendored copy).
    Get-ChildItem -Path $Source -File | Where-Object {
        $_.Name -notin @('anthropic_key.txt')
    } | Copy-Item -Destination $target
    foreach ($sub in @('examples')) {
        $s = Join-Path $Source $sub
        if (Test-Path $s) { Copy-Item $s -Destination $target -Recurse }
    }
    # Vendor the package into <target>\src\woodworking_ai (a resolver candidate),
    # excluding compiled caches.
    $pkgSrc = Join-Path $Source '..\src\woodworking_ai'
    if (-not (Test-Path $pkgSrc)) {
        throw "Cannot vendor package: $pkgSrc not found. Run -Copy from inside the repo."
    }
    $pkgDst = Join-Path $target 'src\woodworking_ai'
    New-Item -ItemType Directory -Path (Split-Path $pkgDst) | Out-Null
    Copy-Item $pkgSrc -Destination $pkgDst -Recurse
    Get-ChildItem $pkgDst -Recurse -Directory -Filter '__pycache__' |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Copied add-in + vendored woodworking_ai into:`n  $target" -ForegroundColor Green
}
else {
    # Directory junction: no admin needed, and realpath() follows it home.
    New-Item -ItemType Junction -Path $target -Target $Source | Out-Null
    Write-Host "Linked (junction):`n  $target`n  -> $Source" -ForegroundColor Green
}

# --- Verify the loader will find the package -----------------------------
$pkgRoot = Resolve-PackageRoot -InstalledDir $target
if ($pkgRoot) {
    Write-Host "Verified: woodworking_ai resolves from $pkgRoot" -ForegroundColor Green
} else {
    Write-Warning ("Add-in installed, but woodworking_ai did NOT resolve. The " +
        "Import/Design commands will error until the package is reachable " +
        "(see the add-in README's Install section).")
}

Write-Host ""
Write-Host "Next steps in Fusion 360:" -ForegroundColor Cyan
Write-Host "  1. Utilities -> Add-Ins -> Scripts and Add-Ins (or Shift+S)."
Write-Host "  2. On the Add-Ins tab, select 'Woodworking AI' and click Run"
Write-Host "     (tick 'Run on Startup' to keep it loaded)."
Write-Host "  3. Buttons appear under Solid -> Create."
Write-Host ""
Write-Host "The 'Design with Woodworking AI' command needs an Anthropic API key:" -ForegroundColor Cyan
Write-Host "  set ANTHROPIC_API_KEY, or put the key in '$AddinName\anthropic_key.txt',"
Write-Host "  or in ~/.woodai/anthropic_key. (Import Spec works without a key.)"
