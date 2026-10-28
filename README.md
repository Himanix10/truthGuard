# TruthGuard Chronos 🛡️⏳

**TruthGuard Chronos** is an AI-powered temporal verification and chronological fact-checking platform. It combines multi-agent reasoning, LangGraph orchestration, and temporal vector indexing (via ChromaDB) to assess claims against chronological context and historical records.

---

## 📁 Project Architecture

```
truthguard-chronos/
│
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entrypoint & middleware
│   │   ├── config.py            # Pydantic environment & app settings
│   │   ├── api/                 # REST API endpoints (/verify, /documents)
│   │   ├── agents/              # Multi-agent verification logic & verifier
│   │   ├── graph/               # LangGraph state schema & graph nodes
│   │   ├── ingestion/           # Document loader, chunking & temporal tagger
│   │   ├── retrieval/           # ChromaDB vector store integration
│   │   └── workflow/            # End-to-end verification orchestration
│   ├── data/
│   │   ├── uploads/             # Raw uploaded document storage
│   │   └── chroma/              # Persistent Chroma vector database
│   ├── requirements.txt         # Backend Python dependencies
│   └── .env                     # Backend environment configuration
│
├── frontend/
│   ├── src/                     # Next.js 14 App Router application
│   │   └── app/                 # Pages, layout, and styling
│   ├── package.json             # Frontend dependencies & scripts
│   ├── tailwind.config.ts       # Tailwind CSS configuration
│   └── tsconfig.json            # TypeScript configuration
│
├── sample_documents/            # Sample documents for temporal testing
│
└── README.md                    # Project documentation
```

---

## 🚀 Quick Start Guide

### 1. Backend Setup (FastAPI & LangGraph)

Navigate to the `backend/` directory:

```bash
cd backend
```

Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

Install backend dependencies:
```bash
pip install -r requirements.txt
```

Configure your environment:
- Review and update `.env` with your API keys (e.g., `OPENAI_API_KEY`).

Start the FastAPI development server:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

### 2. Frontend Setup (Next.js Application)

Navigate to the `frontend/` directory:

```bash
cd ../frontend
```

Install dependencies:
```bash
npm install
```

Start the Next.js development server:
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to view the TruthGuard Chronos interface.

---

## 🧩 Core Subsystems

| Module | Description |
|---|---|
| `app/api` | Exposes REST endpoints for claim verification and document ingestion. |
| `app/agents` | Specialized agents (e.g. Verifier Agent) evaluating claims against evidence. |
| `app/graph` | State definition (`VerificationState`) and LangGraph orchestration graph. |
| `app/ingestion` | Ingests, parses, and slices documents into timestamped chunks. |
| `app/retrieval` | Queries ChromaDB for semantically and chronologically relevant evidence. |
| `app/workflow` | Coordinates verification lifecycle, confidence calculation, and verdict reporting. |

---

## 📄 Sample Testing

Test files are available in `sample_documents/`:
- `sample_timeline_claim.md`: Contains timestamped records to test temporal verification against contradictory or supporting statements.

