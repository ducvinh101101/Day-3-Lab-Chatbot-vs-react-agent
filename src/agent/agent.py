import ast
import re
from typing import List, Dict, Any, Optional
from src.core.llm_provider import LLMProvider
from src.telemetry.metrics import tracker
from src.telemetry.logger import logger

class ReActAgent:
    """
    A ReAct-style Agent that follows the Thought-Action-Observation loop.
    """
    
    def __init__(self, llm: LLMProvider, tools: List[Dict[str, Any]], max_steps: int = 5):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.history = []

    def get_system_prompt(self) -> str:
        tool_descriptions = "\n".join(
            [
                f"- {t['name']}: {t['description']}\n  Args: {t.get('args', 'No args')}"
                for t in self.tools
            ]
        )
        return f"""
You are an intelligent travel booking assistant for Vinpearl Nha Trang that uses ReAct reasoning.
You ONLY answer questions related to finding rooms (tìm phòng) and booking rooms (đặt phòng) at Vinpearl. Do not answer questions on other topics (like weather, general knowledge, history, translation, math, programming, or general chitchat outside of hotel booking).

If the user request is NOT about room availability, packages, room pricing, room itinerary, or booking/reservation at Vinpearl, stop immediately. Do NOT call any tools. Output:
Final Answer: Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Tôi không thể trả lời các câu hỏi ngoài phạm vi này.

You have access to the following tools:
{tool_descriptions}

Follow this exact format:
Thought: short reasoning about the next step.
Action: tool_name(arg_name="value", other_arg=123)
Observation: result of the tool call.
... repeat Thought/Action/Observation until you have enough information.
Final Answer: final recommendation in Vietnamese.

Rules:
- Only use tools listed above.
- Do not invent package availability. Call search_vinpearl_packages first.
- If the user asks for VinWonders, call filter_packages with includes=["VinWonders"].
- Use prepare_booking only after the user has selected a package or provided enough details to reserve one.
- Never call confirm_booking unless the latest user message explicitly says they confirm/agree/chot dat/xac nhan dat.
- Keep the final answer concise and customer-friendly.
"""

    def run(self, user_input: str) -> str:
        logger.log_event("AGENT_START", {"input": user_input, "model": self.llm.model_name})
        
        self.history.append({"role": "user", "content": user_input})
        
        # Build history context (last 3 turns)
        history_context = ""
        if len(self.history) > 1:
            history_context = "Conversation history:\n"
            for msg in self.history[:-1]:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_context += f"{role}: {msg['content']}\n"
            history_context += "\n"
            
        current_prompt = f"{history_context}User request:\n{user_input}"
        steps = 0
        last_response = ""

        while steps < self.max_steps:
            result = self.llm.generate(current_prompt, system_prompt=self.get_system_prompt())
            content = result.get("content", "").strip()
            last_response = content
            tracker.track_request(
                provider=result.get("provider", "unknown"),
                model=self.llm.model_name,
                usage=result.get("usage", {}),
                latency_ms=result.get("latency_ms", 0),
            )
            logger.log_event("AGENT_LLM_RESPONSE", {"step": steps + 1, "content": content})
            
            final_answer = self._parse_final_answer(content)
            if final_answer:
                logger.log_event("AGENT_END", {"steps": steps + 1, "status": "final"})
                self.history.append({"role": "assistant", "content": final_answer})
                return final_answer

            action = self._parse_action(content)
            if not action:
                logger.log_event("AGENT_END", {"steps": steps + 1, "status": "no_action"})
                ans = content or "Agent stopped because no action or final answer was produced."
                self.history.append({"role": "assistant", "content": ans})
                return ans

            tool_name, args = action
            observation = self._execute_tool(tool_name, args)
            logger.log_event(
                "AGENT_TOOL_CALL",
                {"step": steps + 1, "tool": tool_name, "args": args, "observation": observation},
            )

            current_prompt = (
                f"{current_prompt}\n\n"
                f"{content}\n"
                f"Observation: {observation}\n\n"
                "Continue with the next Thought/Action, or provide Final Answer if complete."
            )
            
            steps += 1
            
        logger.log_event("AGENT_END", {"steps": steps, "status": "max_steps"})
        ans = self._fallback_answer(last_response)
        self.history.append({"role": "assistant", "content": ans})
        return ans

    def _execute_tool(self, tool_name: str, args: str) -> str:
        """
        Helper method to execute tools by name.
        """
        for tool in self.tools:
            if tool['name'] == tool_name:
                if "func" not in tool:
                    return f"Tool {tool_name} has no callable implementation."

                try:
                    parsed_args, parsed_kwargs = self._parse_tool_args(args)
                    result = tool["func"](*parsed_args, **parsed_kwargs)
                    return str(result)
                except Exception as exc:
                    logger.error(f"Tool execution failed: {tool_name}")
                    return f"Tool {tool_name} failed: {exc}"
        return f"Tool {tool_name} not found."

    def _parse_action(self, content: str) -> Optional[tuple[str, str]]:
        match = re.search(
            r"Action\s*:\s*(?:```(?:python)?\s*)?([a-zA-Z_][\w]*)\s*\((.*?)\)\s*(?:```)?",
            content,
            re.DOTALL,
        )
        if not match:
            return None
        return match.group(1), match.group(2).strip()

    def _parse_final_answer(self, content: str) -> Optional[str]:
        match = re.search(r"Final Answer\s*:\s*(.*)", content, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def _parse_tool_args(self, args: str) -> tuple[list, dict]:
        if not args:
            return [], {}

        expression = ast.parse(f"_tool_call({args})", mode="eval").body
        if not isinstance(expression, ast.Call):
            raise ValueError("Invalid tool call.")

        parsed_args = [ast.literal_eval(arg) for arg in expression.args]
        parsed_kwargs = {
            kw.arg: ast.literal_eval(kw.value)
            for kw in expression.keywords
            if kw.arg is not None
        }
        return parsed_args, parsed_kwargs

    def _fallback_answer(self, last_response: str) -> str:
        final_answer = self._parse_final_answer(last_response)
        if final_answer:
            return final_answer
        return (
            "Agent reached the maximum number of reasoning steps before producing a final answer. "
            f"Last response: {last_response}"
        )
