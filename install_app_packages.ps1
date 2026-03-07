# Install R packages into hackathon/r_library so run_app.ps1 can find them.
# Run once from the hackathon folder: .\install_app_packages.ps1

$rscript = "C:\Program Files\R\R-4.5.1\bin\Rscript.exe"
if (-not (Test-Path $rscript)) {
    Write-Host "R not found at $rscript. Edit this script if R is installed elsewhere."
    exit 1
}
Set-Location $PSScriptRoot
$rlib = (Join-Path $PSScriptRoot "r_library") -replace "\\", "/"
if (-not (Test-Path (Join-Path $PSScriptRoot "r_library"))) {
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot "r_library") -Force
}
$env:R_LIBS = $rlib
Write-Host "Installing packages into $rlib ..."
& $rscript -e "install.packages(c('leaflet','sf','dplyr','ggplot2','reticulate'), lib = .libPaths()[1L], repos = 'https://cloud.r-project.org')"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Done. You can run .\run_app.ps1 now."
} else {
    Write-Host "Install failed. Check that R and r_library path are correct."
}
