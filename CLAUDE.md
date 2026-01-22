# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an "AI Digital Twin" application - a chatbot that acts as a digital representation of a person, deployed on AWS. The frontend is a Next.js chat interface, and the backend is a FastAPI server using AWS Bedrock for LLM inference.

## Development Commands

### Frontend (Next.js)
```bash
cd frontend
npm install        # Install dependencies
npm run dev        # Development server at http://localhost:3000
npm run build      # Production build (static export to ./out/)
npm run lint       # Run ESLint
```

### Backend (Python/FastAPI)
```bash
cd backend
uv sync                          # Install dependencies (uses uv workspace)
uv run uvicorn server:app --reload --port 8000  # Run development server
uv run deploy.py                 # Build Lambda deployment package (requires Docker)
```

### Full Deployment
```bash
./scripts/deploy.sh [dev|test|prod]  # Deploy entire stack
./scripts/destroy.sh [environment]    # Tear down infrastructure
```

## Architecture

### Frontend (`frontend/`)
- Next.js 16 with static export (configured in `next.config.ts` with `output: 'export'`)
- Single React component `components/twin.tsx` - the chat interface
- Communicates with backend via `NEXT_PUBLIC_API_URL` environment variable
- Styled with Tailwind CSS v4

### Backend (`backend/`)
- FastAPI application in `server.py`
- AWS Lambda deployment via Mangum adapter (`lambda_handler.py`)
- `context.py` - Constructs the LLM system prompt from user data
- `resources.py` - Loads persona data (LinkedIn PDF, facts.json, summary.txt, style.txt) from `data/`
- Conversation history stored in S3 (production) or local `memory/` directory (development)
- Uses AWS Bedrock Converse API with Amazon Nova models (configurable via `BEDROCK_MODEL_ID`)

### Infrastructure (`terraform/`)
- S3 buckets for frontend static hosting and conversation memory
- Lambda function with API Gateway
- CloudFront distribution for frontend
- GitHub OIDC for CI/CD authentication

### Key Environment Variables
- `BEDROCK_MODEL_ID` - Bedrock model (default: `amazon.nova-lite-v1:0`, may need `eu.` or `us.` prefix)
- `USE_S3` / `S3_BUCKET` - Enable S3 for conversation storage
- `CORS_ORIGINS` - Allowed origins for the API
- `NEXT_PUBLIC_API_URL` - Backend API URL for frontend

## Persona Configuration

To configure the digital twin's personality, edit files in `backend/data/`:
- `facts.json` - Basic info including `full_name` and `name`
- `summary.txt` - Personal/professional summary notes
- `style.txt` - Communication style guidelines
- `linkedin.pdf` - LinkedIn profile (optional, extracted via pypdf)
