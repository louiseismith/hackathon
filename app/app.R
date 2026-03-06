# app.R — NYC Urban Risk Early Warning System

# 0. SETUP ----

library(shiny)
library(leaflet)
library(sf)
library(dplyr)
library(reticulate)

# Point reticulate at the project venv (one level up from app/)
venv_path <- file.path(dirname(getwd()), ".venv")
if (!dir.exists(venv_path)) venv_path <- file.path(getwd(), "..", ".venv")
if (dir.exists(venv_path)) use_virtualenv(venv_path, required = TRUE)

# Load .env (look in app dir, then parent)
for (p in c(".", "..")) {
  env_file <- file.path(p, ".env")
  if (file.exists(env_file)) { readRenviron(env_file); break }
}

# Load Python backend
reticulate::source_python(file.path(getwd(), "backend.py"))

# Load + prep GeoJSON boundaries
geojson_path <- file.path(getwd(), "nyc_cd_boundaries.geojson")
cd_boundaries <- st_read(geojson_path, quiet = TRUE) |>
  mutate(cd_id = mapply(function(bcd) {
    result <- borocd_to_cd_id(as.integer(bcd))
    if (is.null(result) || inherits(result, "python.builtin.NoneType")) NA_character_ else result
  }, BoroCD)) |>
  filter(!is.na(cd_id))

# Date range from DB
date_range <- py_to_r(get_date_range())

# Metric definitions: label, column, domain (for color scale), unit
METRICS <- list(
  heat_index_risk     = list(label = "Heat Index Risk",     col = "heat_index_risk",     domain = c(0, 100),  unit = "/ 100"),
  total_capacity_pct  = list(label = "Hospital Capacity %", col = "total_capacity_pct",  domain = c(50, 100), unit = "%"),
  icu_capacity_pct    = list(label = "ICU Capacity %",      col = "icu_capacity_pct",    domain = c(40, 100), unit = "%"),
  ed_wait_hours       = list(label = "ED Wait Hours",       col = "ed_wait_hours",       domain = c(0, 12),   unit = "hrs"),
  transit_delay_index = list(label = "Transit Delay Index", col = "transit_delay_index", domain = c(0, 100),  unit = "/ 100")
)

# 1. UI ----

ui <- fluidPage(
  tags$head(tags$style(HTML("
    body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f5f5f5; }
    .sidebar { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
    .risk-table { font-size: 13px; }
    h4 { font-weight: 600; margin-bottom: 4px; }
    .metric-label { font-size: 11px; color: #888; margin-bottom: 12px; }
  "))),

  titlePanel("NYC Urban Risk — Early Warning System"),

  sidebarLayout(
    sidebarPanel(
      width = 3,
      div(class = "sidebar",
        h4("Controls"),
        dateInput(
          "selected_date", "Date",
          value = date_range$max,
          min   = date_range$min,
          max   = date_range$max
        ),
        selectInput(
          "selected_metric", "Risk Layer",
          choices = setNames(names(METRICS), sapply(METRICS, `[[`, "label")),
          selected = "heat_index_risk"
        ),
        hr(),
        h4("Top Risk Neighborhoods"),
        p(class = "metric-label", "Ranked by selected metric"),
        tableOutput("risk_table")
      )
    ),

    mainPanel(
      width = 9,
      leafletOutput("risk_map", height = "85vh")
    )
  )
)

# 2. SERVER ----

server <- function(input, output, session) {

  # Fetch risk data reactively when date changes
  risk_data <- reactive({
    req(input$selected_date)
    rows <- py_to_r(get_risk_data(as.character(input$selected_date)))
    as.data.frame(do.call(rbind, lapply(rows, function(r) {
      as.data.frame(lapply(r, function(x) if (is.null(x)) NA else x))
    })))
  })

  # Merge spatial + risk data
  map_data <- reactive({
    df <- risk_data()
    cd_boundaries |> left_join(df, by = "cd_id")
  })

  metric_info <- reactive({
    METRICS[[input$selected_metric]]
  })

  # Base map (render once)
  output$risk_map <- renderLeaflet({
    leaflet() |>
      addProviderTiles(providers$CartoDB.Positron) |>
      setView(lng = -73.98, lat = 40.73, zoom = 11)
  })

  # Update polygons when data or metric changes
  observe({
    md    <- map_data()
    mi    <- metric_info()
    col   <- mi$col
    vals  <- as.numeric(md[[col]])
    pal   <- colorNumeric("RdYlGn", domain = mi$domain, reverse = TRUE, na.color = "#cccccc")

    labels <- sprintf(
      "<strong>%s</strong><br/>%s: <b>%.1f</b> %s",
      md$neighborhood, mi$label, vals, mi$unit
    ) |> lapply(htmltools::HTML)

    leafletProxy("risk_map", data = md) |>
      clearShapes() |>
      addPolygons(
        fillColor   = ~pal(vals),
        fillOpacity = 0.75,
        color       = "#ffffff",
        weight      = 1,
        opacity     = 1,
        highlightOptions = highlightOptions(
          weight      = 2,
          color       = "#333",
          fillOpacity = 0.9,
          bringToFront = TRUE
        ),
        label       = labels,
        labelOptions = labelOptions(
          style     = list("font-weight" = "normal", padding = "4px 8px"),
          textsize  = "13px",
          direction = "auto"
        )
      ) |>
      addLegend(
        "bottomright",
        pal    = pal,
        values = mi$domain,
        title  = mi$label,
        layerId = "legend"
      )
  })

  # Top 10 risk table
  output$risk_table <- renderTable({
    df  <- risk_data()
    mi  <- metric_info()
    col <- mi$col
    df |>
      arrange(desc(.data[[col]])) |>
      head(10) |>
      transmute(
        Neighborhood = neighborhood,
        Score = round(.data[[col]], 1)
      )
  }, striped = TRUE, hover = TRUE, bordered = FALSE, class = "risk-table")
}

# 3. RUN ----

shinyApp(ui, server)
