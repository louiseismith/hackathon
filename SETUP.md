# NYC Urban Risk Chatbot — Setup

## Environment and API key

- Ensure a `.env` file exists at the **repository root** (one level above `hackathon/`) with:
  - `OPENAI_API_KEY=your-key-here`
- The agent and API load this via `python-dotenv`; do not commit real keys.

## Python (hackathon / chatbot)

1. From the repo root or from `hackathon/`:
   ```bash
   cd hackathon
   python -m venv .venv
   ```
2. Activate the venv:
   - **Windows:** `.venv\Scripts\activate`
   - **macOS/Linux:** `source .venv/bin/activate`
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   This installs: `pydantic-ai`, `pandas`, `python-dotenv`, `openai`, `fastapi`, `uvicorn`.

## Run the chatbot API

1. **Important:** Run uvicorn **from the `hackathon` folder** (this folder):
   ```powershell
   cd c:\Users\amp388\Desktop\5381\hackathon
   py -m uvicorn chatbot.main:app --host 127.0.0.1 --port 8000
   ```
2. In the browser, open: **http://localhost:8000** or **http://127.0.0.1:8000** (not `0.0.0.0:8000`).
3. Try `/docs` for the API UI, `/health` for a quick check.

### If you get "localhost sent an invalid response"

- Make sure you are in the `hackathon` folder before running uvicorn.
- Run this to test if the app loads (you should see "OK" or an error):
  ```powershell
  cd c:\Users\amp388\Desktop\5381\hackathon
  py -c "from chatbot.main import app; print('OK')"
  ```
- Check the terminal where uvicorn runs for any Python tracebacks.

## R / Shiny (if using Shiny for the dashboard)

- Install **shinychat** for the chat UI:
  ```r
  install.packages("shinychat")
  ```
- Use an HTTP client to call the chatbot API (e.g. `httr::POST()` or `reqres::req_perform()`). Example:
  ```r
  install.packages("httr")   # or "reqres"
  ```
