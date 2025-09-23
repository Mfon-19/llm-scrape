import os
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraping import OpenAIIntentModel, ScrapingEngine, ScrapingEngineConfig

load_dotenv()
app = FastAPI()
frontend_url = os.getenv("FRONTEND_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url] if frontend_url else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmitJobRequest(BaseModel):
    prompt: str
    max_pages: Optional[int] = None


class ScrapeJobResponse(BaseModel):
    plan: Dict[str, object]
    items: List[Dict[str, str]]
    warnings: List[str]
    errors: List[str]
    metadata: Dict[str, object]


intent_model = None
openai_key = os.getenv("OPENAI_API_KEY")
if openai_key:
    intent_model = OpenAIIntentModel(api_key=openai_key, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

engine = ScrapingEngine(config=ScrapingEngineConfig(), intent_model=intent_model)


@app.post("/submit-job", response_model=ScrapeJobResponse)
async def submit_job(req: SubmitJobRequest) -> ScrapeJobResponse:
    try:
        outcome = await engine.run(req.prompt, max_pages=req.max_pages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = outcome.to_dict()
    return ScrapeJobResponse(**result)
