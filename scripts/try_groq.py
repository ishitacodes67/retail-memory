import json
import os

from dotenv import load_dotenv
from groq import Groq

from retail_memory.agent.prompts import SYSTEM_PROMPT_V1
from retail_memory.agent.schemas import ALL_TOOLS

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

with open("evals/questions.jsonl") as f:
    questions = [json.loads(line) for line in f]

for q in questions:
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_V1},
            {"role": "user", "content": q["question"]},
        ],
        tools=ALL_TOOLS,
        tool_choice="auto",
    )
    msg = response.choices[0].message
    print(f"\n[{q['id']}] {q['question']}")
    print(f"  router said: {q['router_result']}")
    if msg.tool_calls:
        for call in msg.tool_calls:
            print(f"  groq called: {call.function.name}({call.function.arguments})")
    else:
        print(f"  groq declined/asked for clarification: {msg.content}")