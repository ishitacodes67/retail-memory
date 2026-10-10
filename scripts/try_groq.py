import os

from dotenv import load_dotenv
from groq import Groq

from retail_memory.agent.schemas import GET_SALES_SUMMARY_TOOL

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

QUESTIONS = [
    "What were the total sales for product 995242 between weeks 1 and 20?",
    "Is product 995242 doing well?",
    "How much revenue would a markdown on product X bring in?",
]

for q in QUESTIONS:
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": q}],
        tools=[GET_SALES_SUMMARY_TOOL],
        tool_choice="auto",
    )
    msg = response.choices[0].message
    print(f"\nQ: {q}")
    if msg.tool_calls:
        for call in msg.tool_calls:
            print(f"  -> called {call.function.name}({call.function.arguments})")
    else:
        print(f"  -> no tool call. Model said: {msg.content}")