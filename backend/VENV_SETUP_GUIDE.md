# Virtual Environment Setup Guide

Follow these steps to set up and run the Python FastAPI backend on Windows (PowerShell) or macOS/Linux.

---

## 1. Prerequisites
- Python 3.10+ installed.
- PowerShell (on Windows) or Terminal (on macOS/Linux).

---

## 2. Navigate to the Backend Folder
```powershell
cd truthguard-chronos/backend
```

---

## 3. Create the Virtual Environment
Create an isolated environment named `.venv`:

**Windows (PowerShell):**
```powershell
python -m venv .venv
```
*(If you have multiple Python versions or use the Python launcher, use `py -3 -m venv .venv`)*

**macOS / Linux:**
```bash
python3 -m venv .venv
```

---

## 4. Activate the Virtual Environment

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

> **Note on Execution Policy:**
> If PowerShell gives an error saying `running scripts is disabled on this system`, allow script execution for the current session by running:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```
> Then run `.\.venv\Scripts\Activate.ps1` again.

**Windows (Command Prompt - cmd):**
```cmd
.\.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

*(Once activated, your terminal prompt will show `(.venv)`)*

---

## 5. Install Dependencies
Install only the basic required packages (`fastapi` and `uvicorn`):

```powershell
pip install -r requirements.txt
```

---

## 6. Run the FastAPI Development Server
Start the server using Uvicorn with auto-reload:

```powershell
uvicorn main:app --reload --port 8000
```

---

## 7. Verify the Endpoints
Open your browser or run curl/Invoke-RestMethod:

- **Root Endpoint (`GET /`):**
  [http://localhost:8000/](http://localhost:8000/)
  Response:
  ```json
  { "message": "TruthGuard-Chronos API is running" }
  ```

- **Health Check (`GET /health`):**
  [http://localhost:8000/health](http://localhost:8000/health)
  Response:
  ```json
  { "status": "healthy" }
  ```

- **Interactive API Documentation (Swagger UI):**
  [http://localhost:8000/docs](http://localhost:8000/docs)

