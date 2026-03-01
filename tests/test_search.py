import asyncio
import os
import sys

# PATH setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent

async def test_search():
    print("Testing Web Search Tool...")
    jada = Agent()
    await jada.init()
    
    prompt = "Dame el titular principal de hoy en España."
    print(f"Prompt: {prompt}")
    
    response = await jada.chat(prompt, user_id="test_user", room_id="search_test")
    print(f"\nResponse:\n{response}")

if __name__ == "__main__":
    asyncio.run(test_search())
