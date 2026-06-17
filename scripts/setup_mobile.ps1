# Run from repo root after installing Flutter SDK:
#   cd mobile
#   flutter create . --org com.taskflow --project-name taskflow_mobile
#   flutter pub get

Write-Host "TaskFlow mobile setup"
if (Get-Command flutter -ErrorAction SilentlyContinue) {
    Set-Location $PSScriptRoot\..\mobile
    flutter create . --org com.taskflow --project-name taskflow_mobile
    flutter pub get
    Write-Host "Done. Run: flutter run"
} else {
    Write-Host "Flutter SDK not found. Install Flutter and re-run this script."
    Write-Host "Lib source code is ready under mobile/lib/"
}
