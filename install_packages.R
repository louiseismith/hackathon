# install_packages.R
# Run this once to install all R dependencies for the NYC Urban Risk app.

cran_packages <- c(
  "shiny",
  "bslib",
  "shinychat",
  "leaflet",
  "sf",        # requires system libraries: brew install gdal geos proj (macOS) or apt-get install libgdal-dev libgeos-dev libproj-dev (Linux)
  "dplyr",
  "reticulate",
  "viridisLite"
)

to_install <- cran_packages[!cran_packages %in% installed.packages()[, "Package"]]

if (length(to_install) > 0) {
  message("Installing: ", paste(to_install, collapse = ", "))
  install.packages(to_install)
} else {
  message("All packages already installed.")
}
