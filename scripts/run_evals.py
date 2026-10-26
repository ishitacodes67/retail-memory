import os

import duckdb
from dotenv import load_dotenv
from groq import Groq

from retail_memory.agent.evals import run_evals, summarize

load_dotenv()
con = duckdb.connect("data/processed/retail.duckdb", read_only=True)
client = Groq(api_key=os.environ["GROQ_API_KEY"])

results = run_evals(con, client)
print(summarize(results))