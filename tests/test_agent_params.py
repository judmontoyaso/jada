from agno.agent import Agent
import inspect

def test_params():
    print("--- FULL AGENT PARAMS ---")
    params = list(inspect.signature(Agent.__init__).parameters.keys())
    for p in sorted(params):
        print(p)
    print("--- END ---")

if __name__ == "__main__":
    test_params()
