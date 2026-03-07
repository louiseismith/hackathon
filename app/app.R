# app.R — NYC Urban Risk Early Warning System (Map-Centric Layout)

# 0. SETUP ----

library(shiny)
library(bslib)
library(shinychat)
library(leaflet)
library(sf)
library(dplyr)
library(ggplot2)
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

# Borough and neighborhood come from community_districts.csv (GeoJSON has only BoroCD)
cd_meta_path <- file.path(getwd(), "..", "data", "community_districts.csv")
if (file.exists(cd_meta_path)) {
  cd_meta <- read.csv(cd_meta_path, stringsAsFactors = FALSE)
  cd_boundaries <- cd_boundaries |> left_join(cd_meta[, c("cd_id", "borough", "neighborhood")], by = "cd_id")
} else {
  cd_boundaries <- cd_boundaries |> mutate(borough = NA_character_, neighborhood = cd_id)
}

# CD lookup for search (no geometry)
cd_lookup <- sf::st_drop_geometry(cd_boundaries) |>
  select(cd_id, borough, neighborhood)

# Date range from DB
date_range <- py_to_r(get_date_range())
date_min <- as.Date(date_range$min)
date_max <- as.Date(date_range$max)
date_seq <- seq(date_min, date_max, by = "day")
months_ord <- month.name[sort(unique(as.integer(format(date_seq, "%m"))))]
years_ord <- sort(unique(format(date_seq, "%Y")))
days_ord <- sprintf("%02d", 1:31)

# Risk layer options (single select)
RISK_LAYERS <- list(
  heat_index_risk     = list(label = "Heat Index",        col = "heat_index_risk",     domain = c(0, 80),   unit = "/ 100"),
  total_capacity_pct  = list(label = "Hospital Capacity", col = "total_capacity_pct",  domain = c(50, 100), unit = "%"),
  transit_delay_index = list(label = "Transit Index",      col = "transit_delay_index", domain = c(0, 60),   unit = ""),
  composite           = list(label = "Composite Score",    col = "composite",           domain = c(0, 100), unit = "/ 100")
)

# Metric definitions for composite (same as before)
METRICS <- list(
  heat_index_risk     = list(label = "Heat Index Risk",     col = "heat_index_risk",     domain = c(0, 80)),
  total_capacity_pct  = list(label = "Hospital Capacity %", col = "total_capacity_pct",  domain = c(50, 100)),
  transit_delay_index = list(label = "Transit Delay Index", col = "transit_delay_index", domain = c(0, 60))
)

# 1. UI ----

ui <- page_fillable(
  title = "NYC Urban Risk — Early Warning System",
  padding = 10,

  tags$head(tags$style(HTML("
    body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background: #f5f5f5; }
    /* Prevent full-page or partial grey overlay - keep dashboard fully visible */
    .offcanvas-backdrop, .modal-backdrop { display: none !important; }
    [class*='sidebar'][class*='backdrop'] { display: none !important; }
    #shiny-disconnected-overlay { display: none !important; }
    .recalculating { opacity: 1 !important; }
    .map-dashboard { position: relative; border-radius: 12px; overflow: hidden; height: calc(100vh - 24px); background: #e0e0e0; display: flex; flex-direction: column; }
    .map-dashboard > div:first-child { flex: 1 1 0; min-height: 400px; height: 100%; position: relative; }
    .map-dashboard #risk_map { height: 100% !important; min-height: 400px !important; }
    .map-dashboard .leaflet { height: 100% !important; min-height: 400px !important; }
    .map-overlay { position: absolute; border-radius: 8px; background: rgba(255,255,255,0.95); box-shadow: 0 2px 8px rgba(0,0,0,0.15); padding: 12px; }
    .overlay-top-bar { top: 12px; left: 12px; right: 12px; display: flex; flex-wrap: nowrap; align-items: center; gap: 10px; padding: 10px 14px; background: rgba(248,249,252,0.92) !important; backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); border: 1px solid rgba(255,255,255,0.6); overflow-x: auto; }
    .overlay-top-bar > * { flex-shrink: 0; }
    .overlay-top-bar .shiny-input-container { margin-bottom: 0; min-height: auto; display: inline-block; width: auto; }
    .overlay-top-bar input, .overlay-top-bar select { border-radius: 8px; border: 1px solid rgba(0,0,0,0.12); background: rgba(255,255,255,0.9); }
    .overlay-top-bar .btn-primary { border-radius: 8px; }
    .overlay-identity { top: 12px; right: 12px; min-width: 200px; }
    /* Hide identity overlay only when it shows the placeholder (no CD selected) */
    .overlay-identity:has(p.text-muted) { display: none !important; }
    .overlay-stats { top: 140px; right: 12px; min-width: 220px; }
    .overlay-top-risk { bottom: 12px; left: 12px; max-width: 380px; max-height: 220px; }
    .overlay-trend { bottom: 12px; right: 12px; width: 320px; height: 200px; }
    .risk-table { font-size: 12px; }
    .stat-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
    .stat-label { color: #555; }
    #sidebar-content { height: calc(100vh - 100px); overflow-y: auto; }
  "))),

  layout_sidebar(
    sidebar = sidebar(
      width = 320,
      id = "main_sidebar",
      title = "NYC Urban Risk",
      navset_card_tab(
        id = "sidebar_tabs",
        full_screen = FALSE,
        nav_panel(
          "Summary",
          div(id = "sidebar-content",
            card(
              card_header("Summary"),
              card_body(uiOutput("summary_text"), style = "min-height: 80px;")
            ),
            card(
              card_header("Recommended Actions"),
              card_body(uiOutput("recommended_actions"), style = "min-height: 60px;")
            )
          )
        ),
        nav_panel(
          "Chatbot",
          div(id = "sidebar-content",
            h6("Suggested prompts", class = "mt-2"),
            actionButton("prompt1", "Which CDs show rising heat and hospital strain?", class = "btn-sm btn-outline-primary w-100 mb-1", style = "text-align: left; white-space: normal;"),
            actionButton("prompt2", "Where is risk accelerating the fastest?",                   class = "btn-sm btn-outline-primary w-100 mb-1", style = "text-align: left; white-space: normal;"),
            actionButton("prompt3", "How does today compare to similar historical patterns?",     class = "btn-sm btn-outline-primary w-100 mb-1", style = "text-align: left; white-space: normal;"),
            actionButton("prompt4", "Which agencies need to coordinate?",                        class = "btn-sm btn-outline-primary w-100 mb-1", style = "text-align: left; white-space: normal;"),
            hr(),
            chat_ui("chat", fill = TRUE, placeholder = "Type your question here...")
          )
        )
      )
    ),
    # Main: map container with overlays
    div(
      class = "map-dashboard",
      leafletOutput("risk_map", width = "100%", height = "70vh"),
      # Top control bar (search, risk layer, date, search button)
      div(
        class = "map-overlay overlay-top-bar",
        textInput("search_cd", NULL, placeholder = "Search your community district...", width = "220px"),
        selectInput("risk_layer", "Risk Layer", choices = setNames(names(RISK_LAYERS), sapply(RISK_LAYERS, `[[`, "label")), width = "160px"),
        selectInput("sel_month", "Month", choices = months_ord, selected = format(date_max, "%B"), width = "110px"),
        selectInput("sel_day", "Day", choices = setNames(days_ord, 1:31), selected = format(date_max, "%d"), width = "70px"),
        selectInput("sel_year", "Year", choices = years_ord, selected = format(date_max, "%Y"), width = "80px"),
        actionButton("btn_search", "Search", icon = icon("search"), class = "btn-primary")
      ),
      # CD identity (top right)
      div(
        class = "map-overlay overlay-identity",
        uiOutput("cd_identity")
      ),
      # Statistics (top right, below identity)
      div(
        class = "map-overlay overlay-stats",
        h6("Statistics", class = "mb-2"),
        uiOutput("cd_statistics")
      ),
      # Top Communities At Risk (bottom left)
      div(
        class = "map-overlay overlay-top-risk",
        h6("Top Communities At Risk", class = "mb-2"),
        tableOutput("top_risk_table")
      ),
      # Trend (bottom right)
      div(
        class = "map-overlay overlay-trend",
        div(class = "d-flex justify-content-between align-items-center mb-1",
          h6("Trend", class = "mb-0"),
          div(
            selectInput("trend_duration", NULL, choices = c("Past 7 Days" = "7", "Past 30 Days" = "30"), width = "100px"),
            actionButton("btn_trend_filter", "Filter", icon = icon("filter"), class = "btn-sm")
          )
        ),
        plotOutput("trend_plot", height = "150px")
      )
    )
  )
)

# 2. SERVER ----

server <- function(input, output, session) {

  # --- Selected date from month/day/year ---
  selected_date <- reactive({
    req(input$sel_month, input$sel_day, input$sel_year)
    m <- match(input$sel_month, month.name)
    if (is.na(m)) m <- as.integer(format(Sys.Date(), "%m"))
    d <- as.integer(input$sel_day)
    y <- as.integer(input$sel_year)
    if (is.na(y)) y <- as.integer(format(Sys.Date(), "%Y"))
    if (is.na(d) || d < 1) d <- 1
    date_str <- sprintf("%04d-%02d-01", y, m)
    last_day <- as.integer(format(as.Date(paste0(date_str, "-01")) + 31 - 1, "%d"))
    d <- pmin(pmax(d, 1), last_day)
    as.Date(sprintf("%04d-%02d-%02d", y, m, d))
  })

  # Keep month/day/year in sync when selected_date is set programmatically
  observe({
    req(selected_date())
    d <- selected_date()
    updateSelectInput(session, "sel_month", selected = format(d, "%B"))
    updateSelectInput(session, "sel_day",   selected = format(d, "%d"))
    updateSelectInput(session, "sel_year",   selected = format(d, "%Y"))
  })

  # --- Selected CD (from map click or search) ---
  selected_cd <- reactiveVal(NULL)

  # Map shape click
  observeEvent(input$risk_map_shape_click, {
    click <- input$risk_map_shape_click
    if (is.null(click) || is.null(click$id)) return()
    row <- cd_lookup[cd_lookup$cd_id == click$id, ][1, ]
    if (nrow(row) > 0)
      selected_cd(list(cd_id = row$cd_id, borough = row$borough, neighborhood = row$neighborhood))
  })

  # Search button: resolve search text to CD
  observeEvent(input$btn_search, {
    q <- trimws(input$search_cd)
    if (is.null(q) || q == "") return()
    q_lower <- tolower(q)
    # Match cd_id (e.g. BX-03) or neighborhood or borough
    match_id  <- which(tolower(cd_lookup$cd_id) == q_lower)
    match_hood <- which(grepl(q_lower, tolower(cd_lookup$neighborhood), fixed = TRUE))
    match_boro <- which(grepl(q_lower, tolower(cd_lookup$borough), fixed = TRUE))
    idx <- c(match_id, match_hood, match_boro)[1]
    if (!is.na(idx)) {
      row <- cd_lookup[idx, ]
      selected_cd(list(cd_id = row$cd_id, borough = row$borough, neighborhood = row$neighborhood))
      # Optional: fly to polygon (would need bounds from sf)
    }
  })

  # --- Risk data ---
  risk_data <- reactive({
    req(selected_date())
    empty_df <- data.frame(
      cd_id = character(0),
      borough = character(0),
      neighborhood = character(0),
      heat_index_risk = numeric(0),
      total_capacity_pct = numeric(0),
      icu_capacity_pct = numeric(0),
      ed_wait_hours = numeric(0),
      transit_delay_index = numeric(0),
      stringsAsFactors = FALSE
    )
    tryCatch({
      rows <- py_to_r(get_risk_data(as.character(selected_date())))
      as.data.frame(do.call(rbind, lapply(rows, function(r) {
        as.data.frame(lapply(r, function(x) if (is.null(x)) NA else x))
      })))
    }, error = function(e) {
      showNotification("Risk data unavailable; showing map without data.", type = "warning", duration = 5)
      empty_df
    })
  })

  map_data <- reactive({
    df <- risk_data()
    cd_boundaries |> left_join(df, by = "cd_id")
  })

  normalize_metric <- function(vals, domain) {
    lo <- domain[1]; hi <- domain[2]
    if (hi <= lo) return(rep(0, length(vals)))
    pmin(pmax((vals - lo) / (hi - lo) * 100, 0), 100)
  }

  # Single risk layer or composite
  composite_data <- reactive({
    df  <- map_data()
    layer <- input$risk_layer
    req(layer)
    if (layer == "composite") {
      normed <- sapply(names(METRICS), function(m) {
        normalize_metric(as.numeric(df[[METRICS[[m]]$col]]), METRICS[[m]]$domain)
      })
      df$display_val <- rowMeans(normed, na.rm = TRUE)
    } else {
      info <- RISK_LAYERS[[layer]]
      df$display_val <- as.numeric(df[[info$col]])
    }
    df
  })

  display_info <- reactive({
    layer <- input$risk_layer
    req(layer)
    RISK_LAYERS[[layer]]
  })

  # --- Map ---
  output$risk_map <- renderLeaflet({
    leaflet() |>
      addProviderTiles(providers$CartoDB.Positron) |>
      setView(lng = -73.98, lat = 40.73, zoom = 11)
  })

  observe({
    cd   <- composite_data()
    di   <- display_info()
    vals <- cd$display_val
    pal  <- colorNumeric(c("#2ecc71", "#f1c40f", "#e67e22", "#e74c3c"), domain = di$domain, na.color = "#cccccc")
    labels <- sprintf(
      "<strong>%s</strong><br/>%s: <b>%.1f</b> %s",
      cd$neighborhood, di$label, vals, di$unit
    ) |> lapply(htmltools::HTML)

    leafletProxy("risk_map", data = cd) |>
      clearShapes() |>
      addPolygons(
        layerId = ~cd_id,
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
      clearControls() |>
      addLegend(
        "bottomright",
        pal     = pal,
        values  = di$domain,
        title   = di$label,
        layerId = "legend"
      )
  })

  # --- CD identity box ---
  output$cd_identity <- renderUI({
    sc <- selected_cd()
    if (is.null(sc)) {
      return(tags$p("Select a district", class = "text-muted mb-0"))
    }
    tagList(
      tags$div(tags$strong(sc$neighborhood), style = "font-size: 1.1em;"),
      tags$div(paste(sc$borough, "/", sc$cd_id), style = "font-size: 0.85em; color: #666;")
    )
  })

  # --- Statistics box ---
  output$cd_statistics <- renderUI({
    sc <- selected_cd()
    rd <- risk_data()
    if (is.null(sc) || is.null(rd)) {
      return(tags$p("—", class = "text-muted"))
    }
    row <- rd[rd$cd_id == sc$cd_id, ][1, ]
    if (is.null(row) || nrow(row) == 0) return(tags$p("—", class = "text-muted"))
    normed <- sapply(names(METRICS), function(m) {
      normalize_metric(as.numeric(row[[METRICS[[m]]$col]]), METRICS[[m]]$domain)
    })
    composite_val <- mean(normed, na.rm = TRUE)
    fmt <- function(x, u) if (is.na(x)) "—" else paste0(round(x, 1), u)
    tagList(
      div(class = "stat-row", span(class = "stat-label", "Heat Index Risk:"),     span(fmt(row$heat_index_risk, " / 100"))),
      div(class = "stat-row", span(class = "stat-label", "Hospital Capacity %:"), span(fmt(row$total_capacity_pct, "%"))),
      div(class = "stat-row", span(class = "stat-label", "ICU Capacity %:"),      span(fmt(row$icu_capacity_pct, "%"))),
      div(class = "stat-row", span(class = "stat-label", "ED Wait Hours:"),       span(fmt(row$ed_wait_hours, ""))),
      div(class = "stat-row", span(class = "stat-label", "Transit Delay Index:"), span(fmt(row$transit_delay_index, ""))),
      div(class = "stat-row", span(class = "stat-label", "Composite Risk Score:"), span(fmt(composite_val, " / 100")))
    )
  })

  # --- Top Communities At Risk table ---
  output$top_risk_table <- renderTable({
    cd <- composite_data()
    di <- display_info()
    req(cd, di)
    tbl <- sf::st_drop_geometry(cd) |>
      arrange(desc(display_val)) |>
      head(10) |>
      transmute(
        Name = paste(neighborhood, cd_id),
        `Risk Type` = di$label,
        `Desired Metric` = if (di$unit == "%") paste0(round(display_val, 1), "%") else round(display_val, 1)
      )
    tbl
  }, striped = TRUE, hover = TRUE, bordered = FALSE, class = "risk-table")

  # --- Trend plot ---
  trend_series <- reactive({
    sc <- selected_cd()
    dur <- as.integer(input$trend_duration)
    req(selected_date(), dur)
    end_d <- selected_date()
    start_d <- end_d - dur + 1
    if (is.null(sc)) return(NULL)
    tryCatch({
      rows <- py_to_r(get_risk_series(sc$cd_id, as.character(start_d), as.character(end_d)))
      if (length(rows) == 0) return(NULL)
      layer <- input$risk_layer
      # Build data.frame from list of rows (each row is named list from Python)
      df <- data.frame(
        date = as.Date(sapply(rows, function(r) r$date)),
        heat_index_risk     = as.numeric(sapply(rows, function(r) r$heat_index_risk)),
        total_capacity_pct  = as.numeric(sapply(rows, function(r) r$total_capacity_pct)),
        transit_delay_index = as.numeric(sapply(rows, function(r) r$transit_delay_index))
      )
      if (layer == "composite") {
        normed <- sapply(names(METRICS), function(m) {
          normalize_metric(df[[METRICS[[m]]$col]], METRICS[[m]]$domain)
        })
        df$display_val <- rowMeans(normed, na.rm = TRUE)
      } else {
        col <- RISK_LAYERS[[layer]]$col
        df$display_val <- df[[col]]
      }
      df
    }, error = function(e) NULL)
  })

  output$trend_plot <- renderPlot({
    df <- trend_series()
    di <- display_info()
    if (is.null(df) || nrow(df) == 0) {
      plot(1, type = "n", axes = FALSE, xlab = "", ylab = "")
      text(1, 1, "Select a district for trend", col = "gray")
      return(invisible(NULL))
    }
    ggplot(df, aes(x = date, y = display_val)) +
      geom_line(color = "steelblue", linewidth = 1) +
      geom_point(color = "steelblue", size = 2) +
      scale_x_date(date_breaks = "2 days", date_labels = "%m/%d") +
      labs(x = NULL, y = di$label) +
      theme_minimal(base_size = 11) +
      theme(axis.text.x = element_text(angle = 45, hjust = 1))
  }, res = 96)

  # --- Summary & Recommended Actions (chatbot) ---
  summary_result <- reactiveVal(list(summary = NULL, actions = NULL))

  observe({
    tab <- input$sidebar_tabs
    sc  <- selected_cd()
    if (is.null(tab) || tab != "Summary") return()
    if (is.null(sc)) {
      summary_result(list(summary = NULL, actions = NULL))
      return()
    }
    summary_result(list(summary = "Loading...", actions = "Loading..."))
    date_str <- as.character(selected_date())
    prompt_summary <- sprintf(
      "Summarize current risk for %s (CD %s) as of %s in 2-3 sentences. Be concise.",
      sc$neighborhood, sc$cd_id, date_str
    )
    prompt_actions <- sprintf(
      "Based on the risk profile for %s (CD %s) as of %s, list 2-3 recommended actions or agencies to coordinate. Be concise.",
      sc$neighborhood, sc$cd_id, date_str
    )
    tryCatch({
      r1 <- chatbot_agent$run_chat(prompt_summary, current_date = date_str, message_history = NULL)
      r2 <- chatbot_agent$run_chat(prompt_actions, current_date = date_str, message_history = NULL)
      summary_result(list(summary = r1$response, actions = r2$response))
    }, error = function(e) {
      summary_result(list(summary = paste("Error:", conditionMessage(e)), actions = ""))
    })
  })

  output$summary_text <- renderUI({
    sr <- summary_result()
    if (is.null(sr$summary)) {
      return(tags$p("Select a community district to see summary.", class = "text-muted"))
    }
    tags$p(sr$summary)
  })

  output$recommended_actions <- renderUI({
    sr <- summary_result()
    if (is.null(sr$actions) || sr$actions == "") {
      return(tags$p("Select a community district to see recommended actions.", class = "text-muted"))
    }
    tags$p(sr$actions)
  })

  # --- Chatbot ---
  chat_history <- reactiveVal(NULL)

  call_chat_api <- function(msg) {
    nid <- showNotification(
      tagList(tags$strong("Thinking..."), " this may take a few seconds"),
      duration = NULL, closeButton = FALSE, type = "message"
    )
    on.exit(removeNotification(nid))
    tryCatch({
      result <- chatbot_agent$run_chat(
        msg,
        current_date    = as.character(selected_date()),
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

  suggest_send <- function(prompt) chat_append("chat", call_chat_api(prompt))
  observeEvent(input$prompt1, suggest_send("Which neighborhoods show rising heat and hospital strain?"))
  observeEvent(input$prompt2, suggest_send("Where is risk accelerating the fastest?"))
  observeEvent(input$prompt3, suggest_send("How does today compare to similar historical patterns?"))
  observeEvent(input$prompt4, suggest_send("Which agencies need to coordinate?"))
}

# 3. RUN ----

shinyApp(ui, server)
