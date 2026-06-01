import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
sys.path.append(str(ROOT))

from src.agent.vinpearl_booking_agent import VinpearlChatAgent
from src.tools.vinpearl_tools import VinpearlToolset


def build_chat_agent():
    load_dotenv()
    toolset = VinpearlToolset()
    
    provider_name = os.getenv("DEFAULT_PROVIDER", "local").lower()
    model_name = os.getenv("DEFAULT_MODEL")
    agent_type = os.getenv("AGENT_TYPE", "extraction").lower()
    
    print(f"Configured Agent Type: {agent_type}")
    
    # Try loading OpenAI if configured
    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and api_key != "your_openai_api_key_here":
            try:
                from src.core.openai_provider import OpenAIProvider
                model = model_name or "gpt-4o"
                print(f"Loading OpenAI Provider with model: {model}")
                return VinpearlChatAgent(toolset=toolset, llm=OpenAIProvider(model_name=model, api_key=api_key), agent_type=agent_type)
            except Exception as exc:
                print(f"Could not load OpenAI provider: {exc}")
                
    # Try loading Gemini if configured
    elif provider_name == "google":
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key and api_key != "your_gemini_api_key_here":
            try:
                from src.core.gemini_provider import GeminiProvider
                model = model_name or "gemini-1.5-flash"
                print(f"Loading Gemini Provider with model: {model}")
                return VinpearlChatAgent(toolset=toolset, llm=GeminiProvider(model_name=model, api_key=api_key), agent_type=agent_type)
            except Exception as exc:
                print(f"Could not load Gemini provider: {exc}")

    # Fallback to Local model
    model_path = os.getenv("LOCAL_MODEL_PATH", "./models/Phi-3-mini-4k-instruct-q4.gguf")
    if os.path.exists(model_path):
        try:
            from src.core.local_provider import LocalProvider
            print(f"Loading Local GGUF Provider: {model_path}")
            return VinpearlChatAgent(toolset=toolset, llm=LocalProvider(model_path=model_path), agent_type=agent_type)
        except Exception as exc:
            print(f"Could not load local model, falling back to rule-based mode: {exc}")
            
    print("No LLM provider loaded. Running in rule-based mode.")
    return VinpearlChatAgent(toolset=toolset, agent_type=agent_type)


CHAT_AGENT = build_chat_agent()


class VinpearlChatHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/inventory":
            self._send_json(self._state_payload())
            return
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(body or "{}")
            message = payload.get("message", "").strip()
            if not message:
                raise ValueError("message is required")
            answer = CHAT_AGENT.run(message)
            self._send_json({"answer": answer, **self._state_payload()})
        except Exception as exc:
            self._send_json({"error": str(exc), **self._state_payload()}, status=400)

    def _state_payload(self):
        toolset = CHAT_AGENT.toolset
        return {
            "mode": CHAT_AGENT.mode,
            "inventory": toolset.get_inventory_snapshot(),
            "pending_booking": toolset.pending_booking,
            "confirmed_bookings": toolset.confirmed_bookings,
        }

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), VinpearlChatHandler)
    print(f"Vinpearl chatbot is running at http://127.0.0.1:{port}")
    print(f"Agent mode: {CHAT_AGENT.mode}")
    server.serve_forever()


if __name__ == "__main__":
    main()
