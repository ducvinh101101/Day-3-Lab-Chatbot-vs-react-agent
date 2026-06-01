import os
import sys

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agent.agent import ReActAgent
from src.tools.vinpearl_tools import build_vinpearl_tools


SCENARIO = """
Tim va dat combo nghi duong Vinpearl Nha Trang 3 ngay 2 dem cho gia dinh 4 nguoi
(2 nguoi lon, 2 tre em) vao cuoi tuan toi, bao gom ve vui choi VinWonders.

Ngay luu tru: 2026-06-05 den 2026-06-07.
"""


def main():
    load_dotenv()
    model_path = os.getenv("LOCAL_MODEL_PATH", "./models/Phi-3-mini-4k-instruct-q4.gguf")

    if not os.path.exists(model_path):
        print(f"Local model not found at: {model_path}")
        print("Dat file .gguf vao duong dan LOCAL_MODEL_PATH trong .env roi chay lai lenh nay.")
        return

    from src.core.local_provider import LocalProvider

    provider = LocalProvider(model_path=model_path)
    agent = ReActAgent(llm=provider, tools=build_vinpearl_tools(), max_steps=5)
    print(agent.run(SCENARIO))


if __name__ == "__main__":
    main()
