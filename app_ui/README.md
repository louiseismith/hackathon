# Python UI — NYC Urban Risk Early Warning System

Streamlit UI that uses the same backend and chatbot as the R Shiny app.

## Run

From the **hackathon** folder (so `.env` and `app/` are found):

```bash
# Windows
python -m streamlit run app_ui/app.py

# Or from app_ui
cd app_ui
streamlit run app.py
```

Ensure the project virtualenv is activated and dependencies are installed (`pip install -r requirements.txt` from `hackathon`).

## Features

- **Map**: NYC community districts colored by risk (heat, hospital capacity, transit, or composite).
- **Search**: Find a district by name or ID; click map tooltips to select.
- **Sidebar**: Summary and recommended actions for the selected district; chatbot tab with suggested prompts.
- **Bottom**: Top communities at risk table and trend chart (after selecting a district).
