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
    # 1. Verify the environment is configured before doing any work
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY environment variable is missing.",
        )

    # 2. Verify the database exists
    if not os.path.exists(DB_PATH):
        raise HTTPException(
            status_code=500,
            detail="Demo database not found. Run scripts/build_demo_db.py first.",
        )

    con = None
    try:
        # Connect read-only for safety in deployment
        con = duckdb.connect(DB_PATH, read_only=True)
        client = Groq(api_key=api_key)
        
        response = answer_question(con, client, request.question)
        
        return ChatResponse(
            status=response.status,
            tool_called=response.tool_called,
            answer=response.final_text,
        )
    except Exception as e:
        # You can add logging here if needed
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 3. Guarantee the connection closes, even if the agent throws an error
        if con is not None:
            con.close()