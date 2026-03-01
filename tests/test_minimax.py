import os
from agno.agent import Agent
from agno.models.nvidia import Nvidia
from dotenv import load_dotenv

load_dotenv()

async def test_minimax():
    print(f"Testing Model: {os.getenv('NVIDIA_MODEL')}")
    agent = Agent(
        model=Nvidia(id=os.getenv("NVIDIA_MODEL")),
        description="Eres un asistente de prueba.",
        markdown=True
    )
    response = await agent.arun("Hola, ¿quién eres?")
    print(f"Response: {response.content}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_minimax())
