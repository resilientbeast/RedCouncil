# RedCouncil

RedCouncil is a multi-agent system where five adversarial AI agents — **Growth, Risk, Legal, TechDebt, and Customer** — simultaneously evaluate a business decision, cross-examine each other, and synthesize a severity-scored verdict. 

Built for the **Qwen Cloud Hackathon, Track 3 (Agent Society)**, RedCouncil demonstrates how diverse AI personas can collaborate (and argue) to produce balanced, risk-aware business intelligence.

## 🌟 Key Features

* **Multi-Agent Debate**: Five specialized agents analyze decisions from their unique mandates.
* **Two-Round Cross-Examination**: 
  * **Round 1**: Independent analysis.
  * **Round 2**: Agents review each other's Round 1 findings and challenge or support them.
* **Conflict Detection Algorithm**: Deterministically identifies when agents are analyzing the same topic but assigning wildly different severities, forcing them to debate.
* **Synthesizer Verdict**: A final agent reviews the debate and produces a conclusive, severity-scored vulnerability report.
* **Real-time Streaming UI**: A React frontend that streams the debate and thoughts of each agent live using Server-Sent Events (SSE).
* **Slack Integration**: Trigger a council session directly from Slack via a `/redcouncil` slash command.
* **Clerk Authentication**: Secure access to the portal.
* **Persistent Storage**: PostgreSQL database integration for decisions and Alibaba Cloud OSS for blob storage.

---

## 🏗️ Architecture

RedCouncil is composed of a FastAPI backend utilizing LangGraph for state management, and a React (Vite) frontend for presentation.

### The Decision Graph (LangGraph)
1. **Decision Input** → A user proposes a business decision (e.g., "Launch a $49/mo tier with no free trial").
2. **Round 1** → 5 agents run in parallel and independently evaluate the decision.
3. **Conflict Detection** → A deterministic algorithm groups findings by topic and detects severity gaps.
4. **Round 2** → The 5 agents run in parallel again, this time with visibility into each other's Round 1 findings and the detected conflicts.
5. **Synthesizer** → A final LLM pass reviews the debate history and generates a standardized `VulnerabilityReport`.

### Technology Stack
* **AI Models**: Qwen-Max for reasoning and Text-Embedding-V3 for semantic matching.
* **Backend**: Python, FastAPI, LangGraph, Pydantic, SQLAlchemy/AsyncPG.
* **Frontend**: React, TypeScript, Vite, Tailwind CSS.
* **Authentication**: Clerk.
* **Storage & Cloud**: PostgreSQL, Alibaba Cloud OSS.

---

## 🚀 Installation & Quickstart

### Prerequisites
- Node.js (v18+)
- Python 3.10+
- An Alibaba Cloud Qwen API Key
- A Clerk Account for authentication

### 1. Backend Setup

Navigate to the `backend` directory and set up a Python virtual environment:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set up your environment variables:
```bash
cp .env.example .env
```
Edit `.env` and fill in the required keys:
* `QWEN_API_KEY`: Your Qwen API key.
* `CLERK_ISSUER`: Your Clerk API URL (e.g., `https://your-app.clerk.accounts.dev`).

Run the FastAPI server:
```bash
uvicorn app.main:app --reload --port 8000
```
The backend will be available at `http://localhost:8000`.

### 2. Frontend Setup

Navigate to the `frontend` directory:
```bash
cd frontend
npm install
```

Set up your environment variables:
```bash
cp .env.example .env
```
Edit `.env` and set:
* `VITE_CLERK_PUBLISHABLE_KEY`: Your Clerk Publishable Key.

Start the development server:
```bash
npm run dev
```
The frontend will be available at `http://localhost:5173` and will proxy API requests to the backend.

### 3. Slack Bot Setup (Optional)

To enable the Slack bot integration:
1. Create a Slack App in your workspace with Socket Mode enabled.
2. Add the `/redcouncil` slash command.
3. Add `chat:write` and `commands` scopes.
4. Update your `backend/.env` with `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and `SLACK_APP_TOKEN`.
5. Run the bot:
```bash
cd backend
python -m app.integrations.slack_bot
```

### 4. Production Deployment

For full production deployment instructions on Alibaba Cloud (ECS, PostgreSQL, SSL, OSS), see [DEPLOYMENT.md](./DEPLOYMENT.md).

---

## 📂 Repository Structure

```text
backend/app/
  models.py                # Pydantic schemas — the data contract
  graph.py                 # LangGraph state machine (rounds + synthesis)
  conflict_detection.py    # Deterministic topic + severity-gap detection
  agents/
    prompts.py             # System prompts for the 5 agents + synthesizer
    qwen_client.py         # Qwen-Max wrapper with schema enforcement
    council.py             # Per-agent execution functions
  integrations/
    slack_bot.py           # Slack presentation layer
  main.py                  # FastAPI app (REST & SSE streaming API)

frontend/src/
  App.tsx                  # Portal shell with Clerk Auth
  hooks/
    useDecisionStream.ts   # SSE consumption + state reducer
  components/              # UI for the council board and verdict report
```

## 📜 License

MIT License. See `LICENSE` for more information.
