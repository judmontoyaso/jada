"""
tests/test_agno.py — Script de verificación local para la migración a Agno.

Este script permite interactuar con el Agente Jada en la terminal,
utilizando la nueva arquitectura basada en `agno.agent.Agent` nativo.
Sirve para verificar el funcionamiento de las tools, SQLite memory
y el flujo de ReAct sin depender del daemon de Matrix.
"""
import sys
import os
import asyncio
from pathlib import Path
import logging

# Asegurar que la raíz del proyecto esté en el PYTHONPATH para importar tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent import Agent

# Silenciar algunos logs de Agno si son muy ruidosos en la terminal
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("agno").setLevel(logging.INFO)

async def main():
    print("🤖 Iniciando Agente Jada (Migración Agno)...")
    
    # 1. Instanciar el agente (crea DB y AgentMemory)
    jada = Agent()
    
    # 2. Inicializar herramientas (conexión a Mongo)
    print("🔌 Conectando a bases de datos (espera unos segundos)...")
    await jada.init()
    
    print("\n✅ Jada está lista. Escribe 'salir' para terminar.")
    print("-" * 50)
    
    # Simulamos un entorno de usuario
    user_id = "@test_user:localhost"
    room_id = "!test_room:localhost"
    
    while True:
        try:
            # Entrada del usuario en la terminal
            promt = input("\nTú: ").strip()
            if not promt:
                continue
                
            if promt.lower() in ("salir", "exit", "quit"):
                print("👋 ¡Hasta luego!")
                break
                
            # Interacción con el agente (chat)
            print("⏳ Pensando...")
            respuesta = await jada.chat(promt, user_id=user_id, room_id=room_id)
            
            # Imprimir respuesta final del Agno Agent
            print(f"\nJada:\n{respuesta}\n")
            print("-" * 50)
            
        except KeyboardInterrupt:
            print("\n👋 ¡Interrumpido!")
            break
        except Exception as e:
            print(f"\n❌ Error durante el test: {e}")

if __name__ == "__main__":
    asyncio.run(main())
