# FORESEEN

## Project Overview

FORESEEN is a Python backend that will eventually help users evaluate the true cost of buying second‑hand products (starting with MacBooks). It will pull market prices via SerpApi, gather experience evidence from web searches, and produce cost‑analysis reports.

## Quick Start (Windows PowerShell)

1. **Verify Python is installed**
   ```powershell
   py --version
   ```
   You should see a version like `Python 3.12.x`.

2. **Create a virtual environment**
   ```powershell
   py -m venv venv
   ```

3. **Activate the virtual environment**
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   (If you get an execution‑policy error, run `Set‑ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.)

4. **Install dependencies**
   ```powershell
   py -m pip install -r requirements.txt
   ```

5. **Configure the SerpApi key**
   - Copy the example file:
     ```powershell
     cp .env.example .env
     ```
   - Open `.env` in your editor and set your key:
     ```
     SERPAPI_API_KEY=your_actual_key_here
     ```
   - **Never** commit `.env` to version control. It is already ignored via `.gitignore`.

6. **Run the backend sanity check**
   ```powershell
   py -m backend.main
   ```
   You should see a message confirming that the SerpApi key is configured, or an error if it is missing.

## Project Structure

```
FORESEEN/
├─ backend/          # Python package containing the application logic
│   ├─ __init__.py
│   └─ main.py       # Entry point – checks the SerpApi key
├─ cache/            # Placeholder for future cached data
├─ tests/            # Placeholder for unit tests
├─ .env.example      # Example environment file (do not edit)
├─ .gitignore        # Ignores virtual env, .env, caches, etc.
├─ requirements.txt  # Minimal dependencies (requests)
└─ README.md         # This file
```

## Next Steps

Once the environment is set up, the next phase will add the actual SerpApi request logic and further modules.
