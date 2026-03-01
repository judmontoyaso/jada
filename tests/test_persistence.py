import asyncio
import os
import sys

# PATH setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent

async def test_persistence():
    print("Testing Memory Persistence...")
    jada = Agent()
    await jada.init()
    
    session_id = "persistence_test_session"
    
    # Run 1: Tell it a fact
    print("\n--- Run 1 ---")
    prompt1 = "Hola Jada, mi color favorito es el púrpura neón."
    print(f"Prompt: {prompt1}")
    res1 = await jada.chat(prompt1, user_id="test_user", room_id=session_id)
    print(f"Jada: {res1}")
    
    # Run 2: Ask about it
    print("\n--- Run 2 ---")
    prompt2 = "¿De qué color te dije que era mi favorito?"
    print(f"Prompt: {prompt2}")
    res2 = await jada.chat(prompt2, user_id="test_user", room_id=session_id)
    print(f"Jada: {res2}")
    
    if "púrpura" in res2.lower() or "neon" in res2.lower():
        print("\n✅ Persistence Test PASSED!")
    else:
        print("\n❌ Persistence Test FAILED!")

if __name__ == "__main__":
    asyncio.run(test_persistence())
