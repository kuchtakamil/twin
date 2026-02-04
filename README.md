# AI Digital Twin

A chatbot that acts as a digital representation of a person. Built with Next.js frontend and FastAPI backend, powered by AWS Bedrock.

**Live demo:** [twin.kamilkuchta.pl](https://twin.kamilkuchta.pl)

## Tech Stack

- **Frontend:** Next.js with static export, Tailwind CSS
- **Backend:** FastAPI, AWS Lambda, AWS Bedrock (Amazon Nova models)
- **Infrastructure:** Terraform, S3, CloudFront, API Gateway

## Local Development

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Backend
```bash
cd backend
uv sync
uv run uvicorn server:app --reload --port 8000
```

## Deployment

```bash
./scripts/deploy.sh [dev|test|prod]
```

## Configuration

Customize the twin's personality by editing files in `backend/data/`:
- `facts.json` - Basic info
- `summary.txt` - Personal/professional summary
- `style.txt` - Communication style guidelines
- `linkedin.pdf` - LinkedIn profile (optional)