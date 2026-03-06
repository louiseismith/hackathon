# NYC Urban Risk Chatbot

## Run the chatbot API (Python)

From the **hackathon** folder (this directory):

```bash
# Optional: create venv and install deps
py -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Ensure .env with OPENAI_API_KEY is in the 5381 folder (parent of hackathon)

# Start the API
py -m uvicorn chatbot.main:app --host 0.0.0.0 --port 8000
```

Then open http://127.0.0.1:8000/docs for the OpenAPI UI, or call `POST /chat` with `{"message": "Which districts are highest risk today?"}`.

## Run the Shiny chat UI (R)

Uses **shinychat** (R). Start the API first (see above), then from R:

```r
setwd("path/to/hackathon")  # or run from hackathon in RStudio
shiny::runApp("app.R")
```

Or set `CHATBOT_URL` if the API is on another host/port (default: http://127.0.0.1:8000).

## Structure

- `chatbot/` — Python package: data_loader, analogs, tools, agent, main (FastAPI)
- `app.R` — Shiny app with shinychat chat panel and suggested prompts
- `data/` — CSVs (heat_index, hospital_capacity, transit_delays, community_districts)
- `CHATBOT_PLAN.md` — Full product and tool spec
