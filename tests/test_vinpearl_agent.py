from typing import Any, Dict, Generator, Optional

from src.agent.agent import ReActAgent
from src.core.llm_provider import LLMProvider
from src.tools.vinpearl_tools import build_vinpearl_tools


class FakeLLMProvider(LLMProvider):
    def __init__(self):
        super().__init__(model_name="fake-local-model")
        self.responses = [
            """Thought: Can tim cac goi Vinpearl Nha Trang dung ngay va so khach.
Action: search_vinpearl_packages(location="Nha Trang", check_in="2026-06-05", check_out="2026-06-07", adults=2, children=2)""",
            """Thought: Yeu cau bat buoc co VinWonders nen can loc goi.
Action: filter_packages(includes=["VinWonders"])""",
            """Thought: Da co goi phu hop, can tao lich trinh 3 ngay 2 dem.
Action: generate_itinerary(duration_days=3, location="Vinpearl Resort & Spa Nha Trang Bay", key_activities=["VinWonders", "Tata Show", "Resort Relaxing"])""",
            """Thought: Da du thong tin de tu van.
Final Answer: De xuat chon Goi C: Villa 2 phong ngu tai Vinpearl Resort & Spa Nha Trang Bay vi phu hop 2 nguoi lon, 2 tre em, bao gom an 3 bua va ve VinWonders. Lich trinh goi y da gom nhan phong, vui choi VinWonders, xem Tata Show va nghi duong tai resort.""",
        ]
        self.index = 0

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        content = self.responses[self.index]
        self.index += 1
        return {
            "content": content,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "latency_ms": 1,
            "provider": "fake",
        }

    def stream(self, prompt: str, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        yield self.generate(prompt, system_prompt)["content"]


def test_vinpearl_agent_react_flow():
    agent = ReActAgent(llm=FakeLLMProvider(), tools=build_vinpearl_tools(), max_steps=5)

    answer = agent.run(
        "Tim combo Vinpearl Nha Trang 3 ngay 2 dem cho 2 nguoi lon, 2 tre em, co VinWonders."
    )

    assert "Goi C" in answer
    assert "VinWonders" in answer
    assert "Tata Show" in answer
