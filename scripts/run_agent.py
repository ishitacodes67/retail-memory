import os

import duckdb
from dotenv import load_dotenv
from groq import Groq

from retail_memory.agent.loop import answer_question

load_dotenv()
con = duckdb.connect("data/processed/retail.duckdb", read_only=True)
client = Groq(api_key=os.environ["GROQ_API_KEY"])

QUESTIONS = [
    "What were the total sales for product 995242 between weeks 1 and 20?",
    "Is product 995242 doing well?",
    "Should I discount product 1127831 assuming a 30% margin?",
]

for q in QUESTIONS:
    r = answer_question(con, client, q)
    print(f"\nQ: {q}")
    print(f"  status: {r.status}")
    if r.invented_params:
        print(f"  invented: {r.invented_params}")
    print(f"  answer: {r.final_text}")