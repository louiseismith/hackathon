# app.R — NYC Urban Risk Early Warning System

# 0. SETUP ----

library(shiny)
library(bslib)
library(shinychat)
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

# Add app/ dir to Python path so chatbot package (app/chatbot/) is importable
py_run_string(paste0('import sys; sys.path.insert(0, r"', normalizePath(getwd()), '")'))

# Import chatbot agent
chatbot_agent <- import("chatbot.agent")

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
  heat_index_risk     = list(label = "Heat Index Risk",     col = "heat_index_risk",     domain = c(0, 80),   unit = "/ 100",
                             desc = "Normalized heat stress score based on temperature and humidity (0–100)."),
  total_capacity_pct  = list(label = "Hospital Capacity %", col = "total_capacity_pct",  domain = c(50, 100), unit = "%",
                             desc = "Share of hospital beds occupied, averaged over the past 7 days."),
  transit_delay_index = list(label = "Transit Delay Index", col = "transit_delay_index", domain = c(0, 60),   unit = "/ 100",
                             desc = "Transit vulnerability score combining network coverage and disruption (0–100). Districts with limited subway/bus access score higher even on calm days.")
)

# 1. UI ----

ui <- navbarPage(
  title = "NYC Urban Risk — Early Warning System",
  id    = "nav",

  tags$head(tags$style(HTML("
    body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f5f5f5; }
    .sidebar { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
    .risk-table { font-size: 13px; }
    h4 { font-weight: 600; margin-bottom: 4px; }
    .metric-label { font-size: 11px; color: #888; margin-bottom: 12px; }
    .cd-panel { background: #f9f9f9; border-left: 3px solid #6c757d; border-radius: 4px; padding: 12px 16px; margin-bottom: 12px; }
    .cd-panel h5 { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: #555; margin-bottom: 8px; }
    .cd-panel .ai-content { font-size: 14px; line-height: 1.6; }
    .cd-panel-summary { border-left-color: #e05c2a; }
    .cd-panel-recs    { border-left-color: #2a7ae0; }
    /* Make chat tab fill the viewport */
    #chat-tab-content { height: calc(100vh - 60px); display: flex; flex-direction: column; }
    #chat-tab-content bslib-sidebar-layout { flex: 1 1 0; min-height: 0; }
    #chat-tab-content #chat_container { height: 100%; }
  "))),

  # --- Tab 1: Map ---
  tabPanel(
    "Map",
    sidebarLayout(
      sidebarPanel(
        width = 3,
        div(class = "sidebar",
          h4("Controls"),
          dateInput(
            "selected_date", "Week ending",
            value = date_range$max,
            min   = date_range$min,
            max   = date_range$max
          ),
          checkboxGroupInput(
            "selected_metrics", "Risk Factors",
            choiceNames  = unname(sapply(METRICS, `[[`, "label")),
            choiceValues = names(METRICS),
            selected     = names(METRICS)
          ),
          div(
            style = "font-size: 11px; color: #666; margin-top: 4px; margin-bottom: 8px; line-height: 1.6;",
            tags$ul(
              style = "padding-left: 14px; margin: 0;",
              lapply(METRICS, function(m) tags$li(tags$strong(m$label), ": ", m$desc))
            )
          ),
          conditionalPanel(
            condition = "input.selected_metrics.length > 1",
            div(
              style = "font-size: 11px; color: #666; margin-top: 6px; margin-bottom: 4px; line-height: 1.4;",
              tags$em(
                "Combined score: each factor is normalized to 0-100 within its typical range,
                 then averaged equally. Higher = greater risk."
              )
            )
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
  ),

  # --- Tab 2: Chatbot ---
  tabPanel(
    "Chatbot",
    div(id = "chat-tab-content",
      layout_sidebar(
        fill = TRUE,
        sidebar = sidebar(
          width = 280,
          h5("Suggested prompts"),
          actionButton("prompt1", "Which neighborhoods show rising heat and hospital strain?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
          actionButton("prompt2", "Where is risk accelerating the fastest?",                   class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
          actionButton("prompt3", "How does today compare to similar historical patterns?",     class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
          actionButton("prompt4", "Is summer heat risk getting worse year over year?",          class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
          actionButton("prompt5", "How has hospital capacity changed since 2020?",              class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
          hr(),
          actionButton("clear_chat", "Clear chat", class = "btn-sm btn-outline-secondary btn-block")
        ),
        uiOutput("chat_container", fill = TRUE)
      )
    )
  )
)

# 2. SERVER ----

server <- function(input, output, session) {

  # --- Chatbot helpers ---
  chat_history <- reactiveVal(NULL)
  chat_generation <- reactiveVal(0)

  output$chat_container <- renderUI({
    chat_generation()  # take dependency so clear button triggers re-render
    chat_ui("chat", fill = TRUE, placeholder = "Ask about NYC Community District risk (e.g. heat, hospital, transit)...")
  })

  call_chat_api <- function(msg) {
    tryCatch({
      result <- chatbot_agent$run_chat(
        msg,
        current_date    = as.character(input$selected_date),
        message_history = chat_history()
      )
      chat_history(result$history)
      result$response
    }, error = function(e) paste0("Chatbot error: ", conditionMessage(e)))
  }

  observeEvent(input$chat_user_input, {
    msg <- input$chat_user_input
    if (is.null(msg) || trimws(msg) == "") return()
    chat_append("chat", call_chat_api(msg))
  })

  observeEvent(input$clear_chat, {
    chat_history(NULL)
    chat_generation(chat_generation() + 1)
  })

  suggest_send <- function(prompt) {
    update_chat_user_input("chat", value = prompt, submit = TRUE)
  }
  observeEvent(input$prompt1, suggest_send("Which neighborhoods show rising heat and hospital strain?"))
  observeEvent(input$prompt2, suggest_send("Where is risk accelerating the fastest?"))
  observeEvent(input$prompt3, suggest_send("How does today compare to similar historical patterns?"))
  observeEvent(input$prompt4, suggest_send("Is summer heat risk getting worse year over year?"))
  observeEvent(input$prompt5, suggest_send("How has hospital capacity changed since 2020?"))

  # --- Map ---

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

  # Normalize a vector to 0-100 given a domain
  normalize_metric <- function(vals, domain) {
    lo <- domain[1]; hi <- domain[2]
    pmin(pmax((vals - lo) / (hi - lo) * 100, 0), 100)
  }

  # Display metadata: single metric or composite
  display_info <- reactive({
    sel <- input$selected_metrics
    req(length(sel) >= 1)
    if (length(sel) == 1) {
      mi <- METRICS[[sel]]
      list(type = "single", label = mi$label, domain = mi$domain, unit = mi$unit, col = mi$col)
    } else {
      list(type = "composite", label = "Combined Risk Score", domain = c(0, 100), unit = "/ 100")
    }
  })

  # Spatial data with display_val column added
  composite_data <- reactive({
    df  <- map_data()
    sel <- input$selected_metrics
    req(length(sel) >= 1)
    if (length(sel) == 1) {
      df$display_val <- as.numeric(df[[METRICS[[sel]]$col]])
    } else {
      normed <- sapply(sel, function(m) {
        normalize_metric(as.numeric(df[[METRICS[[m]]$col]]), METRICS[[m]]$domain)
      })
      df$display_val <- rowMeans(normed, na.rm = TRUE)
    }
    df
  })

  # Base map (render once)
  output$risk_map <- renderLeaflet({
    leaflet() |>
      addProviderTiles(providers$CartoDB.Positron) |>
      setView(lng = -73.98, lat = 40.73, zoom = 11)
  })

  # Update polygons when data or metric selection changes
  observe({
    cd   <- composite_data()
    di   <- display_info()
    vals <- cd$display_val
    pal  <- colorNumeric("plasma", domain = di$domain, reverse = FALSE, na.color = "#cccccc")

    if (di$type == "single") {
      labels <- sprintf(
        "<strong>%s</strong><br/>%s: <b>%.1f</b> %s",
        cd$neighborhood, di$label, vals, di$unit
      ) |> lapply(htmltools::HTML)
    } else {
      sel <- input$selected_metrics
      labels <- lapply(seq_len(nrow(cd)), function(i) {
        detail <- paste(sapply(sel, function(m) {
          sprintf("%s: %.1f %s",
                  METRICS[[m]]$label,
                  as.numeric(cd[[METRICS[[m]]$col]][i]),
                  METRICS[[m]]$unit)
        }), collapse = "<br/>")
        htmltools::HTML(paste0(
          "<strong>", cd$neighborhood[i], "</strong><br/>",
          "Combined Risk: <b>", round(vals[i], 1), "</b> / 100<br/>",
          detail
        ))
      })
    }

    leafletProxy("risk_map", data = cd) |>
      clearShapes() |>
      addPolygons(
        layerId     = ~cd_id,
        fillColor   = ~pal(vals),
        fillOpacity = 0.75,
        color       = "#ffffff",
        weight      = 1,
        opacity     = 1,
        highlightOptions = highlightOptions(
          weight       = 2,
          color        = "#333",
          fillOpacity  = 0.9,
          bringToFront = TRUE
        ),
        label        = labels,
        labelOptions = labelOptions(
          style     = list("font-weight" = "normal", padding = "4px 8px"),
          textsize  = "13px",
          direction = "auto"
        )
      ) |>
      addLegend(
        "bottomright",
        pal     = pal,
        values  = di$domain,
        title   = di$label,
        layerId = "legend"
      )
  })

  # --- CD click: AI summary modal ---

  selected_cd <- reactiveVal(NULL)

  observeEvent(input$risk_map_shape_click, {
    click <- input$risk_map_shape_click
    cd_id <- click$id
    if (is.null(cd_id) || cd_id == "") return()

    # Lookup neighborhood name from current map data
    cd_data <- sf::st_drop_geometry(composite_data())
    row      <- cd_data[cd_data$cd_id == cd_id, ]
    nbhd     <- if (nrow(row) > 0) row$neighborhood[1] else cd_id

    selected_cd(cd_id)

    showModal(modalDialog(
      title     = paste0(nbhd, " (", cd_id, ")"),
      size      = "l",
      easyClose = TRUE,
      footer    = modalButton("Close"),
      div(class = "cd-panel cd-panel-summary",
        tags$h5("Risk Overview"),
        div(class = "ai-content", uiOutput("cd_summary_ui"))
      ),
      div(class = "cd-panel cd-panel-recs",
        tags$h5("Decision Signals"),
        div(class = "ai-content", uiOutput("cd_recs_ui"))
      )
    ))
  })

  output$cd_summary_ui <- renderUI({
    cd <- selected_cd()
    req(cd)
    result <- tryCatch(
      chatbot_agent$run_cd_summary(cd, as.character(input$selected_date)),
      error = function(e) paste0("Error generating summary: ", conditionMessage(e))
    )
    shiny::markdown(result)
  })

  output$cd_recs_ui <- renderUI({
    cd <- selected_cd()
    req(cd)
    result <- tryCatch(
      chatbot_agent$run_cd_recommendations(cd, as.character(input$selected_date)),
      error = function(e) paste0("Error generating recommendations: ", conditionMessage(e))
    )
    shiny::markdown(result)
  })

  # Top 10 risk table
  output$risk_table <- renderTable({
    cd <- composite_data()
    sf::st_drop_geometry(cd) |>
      arrange(desc(display_val)) |>
      head(10) |>
      transmute(
        Neighborhood = neighborhood,
        Score = round(display_val, 1)
      )
  }, striped = TRUE, hover = TRUE, bordered = FALSE, class = "risk-table")
}

# 3. RUN ----

shinyApp(ui, server)
