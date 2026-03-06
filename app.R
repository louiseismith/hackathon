#
# NYC Urban Risk — Shiny Chat UI
# Uses shinychat (R package) for the chat panel. Wire to chatbot API at http://localhost:8000/chat.
# Start the API first: from hackathon folder run: py -m uvicorn chatbot.main:app --host 0.0.0.0 --port 8000
#

library(shiny)
library(bslib)
library(shinychat)
library(httr)

CHATBOT_URL <- Sys.getenv("CHATBOT_URL", "http://127.0.0.1:8000")

ui <- page_fillable(
  title = "NYC Urban Risk — Decision Support",
  theme = bs_theme(bootswatch = "flatly"),
  layout_sidebar(
    sidebar = sidebar(
      width = 280,
      h5("Suggested prompts"),
      actionButton("prompt1", "Which districts are highest risk today?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
      actionButton("prompt2", "Where is risk accelerating the fastest?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
      actionButton("prompt3", "Which districts show rising heat and hospital strain?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
      actionButton("prompt4", "How does today compare to similar historical patterns in BX-03?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
      actionButton("prompt5", "Which agencies need to coordinate for QN-04 today?", class = "btn-block mb-2", style = "text-align: left; white-space: normal;"),
      hr(),
      p("Chat UI: shinychat (R). Backend: FastAPI + PydanticAI.", class = "text-muted small")
    ),
    main = mainPanel(
      width = 8,
      chat_ui("chat", fill = TRUE, placeholder = "Ask about NYC Community District risk (e.g. heat, hospital, transit)...")
    )
  )
)

server <- function(input, output, session) {
  call_chat_api <- function(msg) {
    tryCatch({
      r <- POST(
        paste0(CHATBOT_URL, "/chat"),
        body = list(message = msg),
        encode = "json",
        timeout(120)
      )
      if (status_code(r) != 200) {
        return(paste0("API error: ", status_code(r), " — Is the chatbot API running at ", CHATBOT_URL, "?"))
      }
      content(r)$reply
    }, error = function(e) {
      paste0("Could not reach chatbot API: ", conditionMessage(e), ". Start it with: py -m uvicorn chatbot.main:app --port 8000")
    })
  }

  # User typed and sent a message (chat_ui shows the user message; we append assistant reply only)
  observeEvent(input$chat_user_input, {
    msg <- input$chat_user_input
    if (is.null(msg) || trimws(msg) == "") return()
    reply <- call_chat_api(msg)
    chat_append("chat", reply, role = "assistant")
  })

  # Suggested prompt buttons
  suggest_send <- function(prompt) {
    chat_append("chat", paste0("**You:** ", prompt), role = "user")
    reply <- call_chat_api(prompt)
    chat_append("chat", reply, role = "assistant")
  }

  observeEvent(input$prompt1, suggest_send("Which districts are highest risk today?"))
  observeEvent(input$prompt2, suggest_send("Where is risk accelerating the fastest?"))
  observeEvent(input$prompt3, suggest_send("Which community districts show rising heat and hospital strain?"))
  observeEvent(input$prompt4, suggest_send("How does today compare to similar historical patterns in BX-03?"))
  observeEvent(input$prompt5, suggest_send("Which agencies need to coordinate for QN-04 today?"))
}

shinyApp(ui, server)
