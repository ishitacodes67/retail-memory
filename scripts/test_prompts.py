import os
import duckdb
from dotenv import load_dotenv
from groq import Groq

from retail_memory.agent.loop import answer_question
from retail_memory.agent.prompts import SYSTEM_PROMPT_V1

load_dotenv()
con = duckdb.connect("data/processed/retail.duckdb", read_only=True)
client = Groq(api_key=os.environ["GROQ_API_KEY"])

with open("prompts/v2.txt", "r", encoding="utf-8") as f:
    V2 = f.read()

Q = "What's the sales summary for product 1127831 between weeks 1 and 20, and should I discount it assuming a 30% margin?"

for prompt_text, label in [(SYSTEM_PROMPT_V1, "v1"), (V2, "v2")]:
    print(f"\n--- {label} ---")
    for i in range(3):
        r = answer_question(con, client, Q, system_prompt=prompt_text)
        print(f"[{label} run {i+1}]")
        print(r.final_text)
        print("-" * 40)