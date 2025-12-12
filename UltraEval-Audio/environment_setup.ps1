& C:/Localrepos/voicelive-evaluation/.venv/Scripts/Activate.ps1 
$env:PYTHONPATH = "C:\Localrepos\voicelive-evaluation\UltraEval-Audio"
$env:CUDA_VISIBLE_DEVICES = "0"
Write-Host "Environment setup:" -ForegroundColor Cyan
Write-Host "  PYTHONPATH: $env:PYTHONPATH" -ForegroundColor Gray
Write-Host "  CUDA_VISIBLE_DEVICES: $env:CUDA_VISIBLE_DEVICES" -ForegroundColor Gray
Write-Host "  Working Directory: $(Get-Location)" -ForegroundColor Gray