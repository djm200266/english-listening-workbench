# create-desktop-shortcut.ps1 - Create desktop shortcut for English Listening Workbench
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$targetPath = Join-Path $root "start-workbench.cmd"
if (-not (Test-Path $targetPath)) {
    Write-Host "ERROR: start-workbench.cmd not found at $targetPath" -ForegroundColor Red
    Write-Host "Press Enter to exit..." ; Read-Host
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "英语听说课工作台.lnk"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Create Desktop Shortcut" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Target  : $targetPath" -ForegroundColor White
Write-Host "  Desktop : $shortcutPath" -ForegroundColor White

# Check for existing shortcut
if (Test-Path $shortcutPath) {
    Write-Host ""
    Write-Host "  Shortcut already exists at:" -ForegroundColor Yellow
    Write-Host "  $shortcutPath" -ForegroundColor Yellow
    Write-Host ""
    $answer = Read-Host "  Overwrite? (y/n)"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Write-Host "  Cancelled." -ForegroundColor Gray
        Write-Host "Press Enter to exit..." ; Read-Host
        exit 0
    }
    Remove-Item $shortcutPath -Force
    Write-Host "  Removed old shortcut." -ForegroundColor Gray
}

# Create shortcut using WScript.Shell COM object
$wsShell = New-Object -ComObject WScript.Shell
$shortcut = $wsShell.CreateShortcut($shortcutPath)

$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7  # Minimized window
$shortcut.Description = "English Listening Workbench - 七年级英语听说课多模态生成与质量评测工作台"

# Try to use icon if available
$iconPath = Join-Path $root "icon.ico"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
} else {
    # Use cmd.exe icon as fallback
    $shortcut.IconLocation = "cmd.exe,0"
}

$shortcut.Save()

# Verify
if (Test-Path $shortcutPath) {
    Write-Host ""
    Write-Host "  Shortcut created successfully!" -ForegroundColor Green
    Write-Host "  $shortcutPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Double-click '英语听说课工作台' on your desktop to start." -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "  ERROR: Failed to create shortcut." -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to exit..." -ForegroundColor Gray
Read-Host
