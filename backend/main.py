import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
frontend_url = os.getenv("FRONTEND_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmitJobRequest(BaseModel):
    prompt: str


@app.post("/submit-job")
async def say_hello(req: SubmitJobRequest):
    return {"message": f"Request acknowledged: {req.prompt}"}
