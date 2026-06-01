from typing import Any, Dict, Generator, Optional
import json

from src.agent.vinpearl_booking_agent import ExtractionBasedVinpearlAgent
from src.core.llm_provider import LLMProvider
from src.tools.vinpearl_tools import VinpearlToolset


class FakeJSONLLMProvider(LLMProvider):
    def __init__(self, json_output: str):
        super().__init__(model_name="fake-json-model")
        self.json_output = json_output

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        return {
            "content": self.json_output,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "latency_ms": 1,
            "provider": "fake",
        }

    def stream(self, prompt: str, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        yield self.generate(prompt, system_prompt)["content"]


def test_extraction_agent_search():
    json_response = {
        "intent": "search",
        "location": "Nha Trang",
        "check_in": "2026-06-05",
        "check_out": "2026-06-07",
        "adults": 2,
        "children": 2,
        "max_price": 15000000,
        "includes": ["VinWonders"],
        "package_code": None,
        "guest_name": None
    }
    
    provider = FakeJSONLLMProvider(json.dumps(json_response))
    agent = ExtractionBasedVinpearlAgent(VinpearlToolset(), provider)
    
    answer = agent.run("Tìm phòng cho 2 người lớn, 2 trẻ em có VinWonders ngày 5/6 đến 7/6/2026 dưới 15 triệu")
    
    assert "DLX-SEAVIEW-BB" not in answer  # filtered out because it does not include VinWonders
    assert "FAM-SUITE-VW" in answer       # fits all criteria, under 15 million
    assert "VILLA-2BR-FB-VW" not in answer # filtered out because total price (21.6m) exceeds 15 million cap
    assert "Lịch trình gợi ý" not in answer
    assert "Nguyễn Văn" not in answer     # no booking yet
