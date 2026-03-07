# Run the Shiny app without needing Rscript on PATH.
# Use: .\run_app.ps1   (from the hackathon folder)
# Packages (shiny, bslib, shinychat, httr) are in r_library/ so no admin rights are needed.

$rscript = "C:\Program Files\R\R-4.5.1\bin\Rscript.exe"
if (-not (Test-Path $rscript)) {
    Write-Host "R not found at $rscript. Edit this script if R is installed elsewhere."
    exit 1
}
Set-Location $PSScriptRoot
# Use project r_library so packages work without writable system R library
$rlib = (Join-Path $PSScriptRoot "r_library") -replace "\\", "/"
$env:R_LIBS = $rlib
& $rscript -e "shiny::runApp('app')"
