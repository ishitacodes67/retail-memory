"""FastAPI backend for Retail Memory."""

import os

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from groq import Groq
from pydantic import BaseModel

from retail_memory.agent.loop import answer_question

load_dotenv()

app = FastAPI(title="Retail Memory API")

DB_PATH = "data/processed/demo.duckdb"


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    status: str
    tool_called: str | None
    answer: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    try:
        if not os.path.exists(DB_PATH):
            raise HTTPException(
                status_code=500,
                detail="Demo database not found. Run scripts/build_demo_db.py first.",
            )
        
        con = duckdb.connect(DB_PATH, read_only=True)
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        
        response = answer_question(con, client, request.question)
        con.close()
        
        return ChatResponse(
            status=response.status,
            tool_called=response.tool_called,
            answer=response.final_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))