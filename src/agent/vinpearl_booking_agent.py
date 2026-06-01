import json
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.agent.agent import ReActAgent
from src.core.llm_provider import LLMProvider
from src.tools.vinpearl_tools import CONFIRM_KEYWORDS, VinpearlToolset, _normalize, _format_money


def _is_pure_greeting(text: str) -> bool:
    normalized = _normalize(text).strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    greetings = ["chao", "hello", "hi", "helo", "xin chao", "chao ban", "chao ad", "chao bot", "chao assistant"]
    if normalized in greetings:
        return True
    words = normalized.split()
    if len(words) <= 2 and any(g in words for g in ["chao", "hello", "hi", "helo", "xin"]):
        # Check that it doesn't contain important booking keywords
        booking_keywords = ["phong", "dat", "book", "tim", "gia", "combo"]
        if not any(k in normalized for k in booking_keywords):
            return True
    return False


def _is_relevant(text: str, pending_booking: bool = False) -> bool:
    normalized = _normalize(text).strip()
    # Replace punctuation with spaces
    cleaned = re.sub(r"[^\w\s]", " ", normalized)
    words = set(cleaned.split())
    
    # 1. Package code check (e.g. FAM-SUITE-VW)
    package_codes = re.findall(r"\b([A-Z0-9]+(?:-[A-Z0-9]+)+)\b", text.upper())
    if package_codes:
        return True
        
    # 2. Price pattern check (e.g. 28.400.000, 28,400,000, 28400000, 5 trieu, etc.)
    if re.search(r"\b\d[\d.,]{5,}\b", normalized) or "trieu" in normalized or "million" in normalized:
        return True
        
    # 3. Confirmation check if there is a pending booking
    if pending_booking:
        confirmations = ["xac nhan", "dong y", "chot", "confirm", "ok", "oke", "yep", "yes", "dung vay", "chinh xac"]
        if any(keyword in normalized for keyword in confirmations):
            return True
            
    # 4. Relevant single-word keywords (must match exactly as a full word)
    single_word_keywords = {
        "phong", "dat", "book", "tim", "gia", "tien", "combo", "goi",
        "package", "villa", "suite", "deluxe", "resort", "hotel",
        "ngay", "dem", "khach", "confirm", "ok", "oke", "yep", "yes",
        "tata", "buffet", "vnd"
    }
    
    if any(keyword in words for keyword in single_word_keywords):
        return True
        
    # 5. Relevant multi-word phrases (must match as a substring with word boundaries)
    multi_word_phrases = [
        "check in", "check_in", "check out", "check_out", 
        "nguoi lon", "tre em", "khach san", "vinwonders", "vin wonders",
        "vui choi", "an sang", "an ba bua", "chi phi", "tra cuu", "kiem tra"
    ]
    
    for phrase in multi_word_phrases:
        if phrase in normalized:
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, normalized):
                return True
                
    # 6. Specific price question context (e.g. contains "bao nhieu" and at least one other booking word)
    if "bao nhieu" in normalized:
        pattern = r"\bbao nhieu\b"
        if re.search(pattern, normalized):
            query_context = ["phong", "gia", "combo", "goi", "resort", "villa", "suite", "deluxe", "ve", "booking", "tien", "chi phi"]
            if any(context_word in words for context_word in query_context):
                return True
                
    return False


def normalize_max_price(val: Optional[int]) -> Optional[int]:
    if val is None:
        return None
    if val <= 0:
        return None
    # If the value is very small (less than 1000), it's in millions (e.g., 10 -> 10,000,000)
    if val < 1000:
        return val * 1_000_000
    # If the value is between 1000 and 99999, it's in thousands (e.g., 10000 -> 10,000,000)
    if val < 100_000:
        return val * 1_000
    return val


def _extract_specific_price(text: str) -> Optional[int]:
    normalized = _normalize(text)
    million_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:trieu|million)", normalized)
    if million_match:
        val = float(million_match.group(1).replace(",", "."))
        return int(val * 1_000_000)

    money_match = re.search(r"(\d[\d.,]{5,})\s*(?:vnd|dong|d)?", normalized)
    if money_match:
        digits = re.sub(r"\D", "", money_match.group(1))
        return int(digits) if digits else None
    return None


def _describe_room_package(package: Dict[str, Any]) -> str:
    code = package.get("package_code") or package.get("code")
    name = package.get("room_name") or package.get("name") or ""
    # Accent correction
    name = name.replace("huong bien", "hướng biển").replace("kem", "kèm").replace("phong ngu", "phòng ngủ")
    
    resort = package.get("resort") or ""
    
    includes_list = package.get("includes") or []
    includes_vi = []
    for inc in includes_list:
        inc_vi = inc.replace("Phong o", "Phòng ở")\
                    .replace("An sang buffet", "Ăn sáng buffet")\
                    .replace("Ve VinWonders", "Vé VinWonders")\
                    .replace("An 3 bua", "Ăn 3 bữa")\
                    .replace("Xe dien noi khu", "Xe điện nội khu")
        includes_vi.append(inc_vi)
    includes = " + ".join(includes_vi)
    
    price_str = ""
    if "total_price" in package:
        price_str = f"tổng giá {_format_money(package['total_price'])}"
    else:
        base_p = package.get("base_price_per_night") or package.get("base_price") or 0
        weekend_p = package.get("weekend_price_per_night") or package.get("weekend_price") or 0
        price_str = f"giá từ {_format_money(base_p)}/đêm (cuối tuần {_format_money(weekend_p)}/đêm)"
        
    capacity = package.get("capacity") or f"{package.get('capacity_adults', 2)} người lớn, {package.get('capacity_children', 0)} trẻ em"
    capacity = capacity.replace("adults", "người lớn").replace("children", "trẻ em")
    
    resort_str = f" tại {resort}" if resort else ""
    
    return f"Gói {code}: {name}{resort_str} | {price_str} | Bao gồm: {includes} | Sức chứa: {capacity}."


class RuleBasedVinpearlAgent:
    """
    Deterministic fallback for the chatbot UI when the local GGUF model is not
    available yet. It uses the same local tools and keeps the confirmation guard.
    """

    def __init__(self, toolset: VinpearlToolset):
        self.toolset = toolset
        self.history: List[Dict[str, str]] = []
        if not hasattr(self.toolset, "last_max_price"):
            self.toolset.last_max_price = None
        if not hasattr(self.toolset, "last_includes"):
            self.toolset.last_includes = []

    def _handle_lookup(self, user_input: str) -> Optional[str]:
        # 1. Check for package code
        package_code = self._extract_package_code(user_input)
        if package_code:
            # Find in last search/filtered results
            package = self.toolset._find_package(package_code)
            if package:
                return f"Thông tin về gói {package_code}:\n{_describe_room_package(package)}"
            # Find in all inventory rooms
            room = self.toolset._find_room(package_code)
            if room:
                resort_name = ""
                for resort in self.toolset.inventory["resorts"]:
                    if any(r["code"] == room["code"] for r in resort["rooms"]):
                        resort_name = resort["name"]
                        break
                room_copy = dict(room)
                room_copy["resort"] = resort_name
                return f"Thông tin về gói {package_code}:\n{_describe_room_package(room_copy)}"
                
        # 2. Check for price
        price = _extract_specific_price(user_input)
        if price is not None:
            # Find in last search/filtered results matching total_price
            for pkg in (self.toolset.last_filtered_results or self.toolset.last_search_results):
                if pkg.get("total_price") == price:
                    return f"Phòng có giá {_format_money(price)} trong danh sách lựa chọn phù hợp gần nhất là:\n{_describe_room_package(pkg)}"
            # Find in inventory matching base_price or weekend_price
            for resort in self.toolset.inventory["resorts"]:
                for room in resort["rooms"]:
                    if room.get("base_price_per_night") == price or room.get("weekend_price_per_night") == price:
                        room_copy = dict(room)
                        room_copy["resort"] = resort["name"]
                        return f"Phòng có giá {_format_money(price)} trong hệ thống là:\n{_describe_room_package(room_copy)}"
                        
        return None

    def run(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        normalized = _normalize(user_input)

        # 1. Check for greeting first
        if _is_pure_greeting(user_input):
            answer = "Chào bạn! Tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Bạn cần hỗ trợ tìm phòng hay đặt phòng cho thời gian nào ạ?"
            self.history.append({"role": "assistant", "content": answer})
            return answer

        # 2. Check for specific lookup query
        lookup_answer = self._handle_lookup(user_input)
        if lookup_answer:
            self.history.append({"role": "assistant", "content": lookup_answer})
            return lookup_answer

        # 3. Check for relevance
        has_pending = self.toolset.pending_booking is not None
        if not _is_relevant(user_input, pending_booking=has_pending):
            answer = "Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Tôi không thể trả lời các câu hỏi ngoài phạm vi này."
            self.history.append({"role": "assistant", "content": answer})
            return answer

        # 4. Proceed with original flow
        if self._has_confirmation(normalized) and self.toolset.pending_booking:
            pending_id = self.toolset.pending_booking["booking_id"]
            answer = self.toolset.confirm_booking(pending_id, user_input)
            self.history.append({"role": "assistant", "content": answer})
            return answer

        package_code = self._extract_package_code(user_input)
        if package_code and any(word in normalized for word in ["giu cho", "tao booking", "dat tam", "dat phong"]):
            guest_name = self._extract_guest_name(user_input) or "Khach Vinpearl"
            
            # Extract dates from input if specified
            dates = self._extract_dates(user_input)
            check_in = None
            check_out = None
            if len(dates) >= 2:
                check_in, check_out = dates[0], dates[1]
            elif len(dates) == 1:
                check_in_date = date.fromisoformat(dates[0])
                check_in = check_in_date.isoformat()
                check_out = (check_in_date + timedelta(days=1)).isoformat()
                
            answer = self.toolset.prepare_booking(
                package_code=package_code,
                guest_name=guest_name,
                check_in=check_in,
                check_out=check_out
            )
            self.history.append({"role": "assistant", "content": answer})
            return answer

        search_params = self._extract_search_params(user_input)
        
        # Check if the user specified a new max price or if we should carry over
        max_price = self._extract_max_price(user_input)
        if max_price is not None:
            self.toolset.last_max_price = max_price
        elif any(phrase in normalized for phrase in ["khong gioi han gia", "gia nao cung duoc", "bo loc gia", "bo gia"]):
            self.toolset.last_max_price = None
        
        # Check for VinWonders mention to update filter
        if "vinwonders" in normalized:
            if "VinWonders" not in self.toolset.last_includes:
                self.toolset.last_includes.append("VinWonders")
        elif any(w in normalized for w in ["khong can vinwonders", "bo vinwonders", "khong lay vinwonders"]):
            if "VinWonders" in self.toolset.last_includes:
                self.toolset.last_includes.remove("VinWonders")

        observation = self.toolset.search_vinpearl_packages(**search_params)
        
        effective_max_price = self.toolset.last_max_price
        effective_includes = self.toolset.last_includes
        
        if effective_includes or effective_max_price is not None:
            observation = self.toolset.filter_packages(includes=effective_includes, max_price=effective_max_price)

        # Convert output to proper accented Vietnamese
        observation_clean = observation.replace("Cac lua chon phu hop:", "Các lựa chọn phù hợp:")
        observation_clean = observation_clean.replace("Lua chon sau khi loc:", "Lựa chọn sau khi lọc:")
        
        answer = (
            f"{observation_clean}\n\n"
            "Nếu muốn giữ chỗ, hãy nhấn: dat tam <ma goi> cho <ten khach>. "
            "Tôi chỉ xác nhận đặt khi bạn nói rõ 'xác nhận đặt' hoặc 'chốt đặt'."
        )
        self.history.append({"role": "assistant", "content": answer})
        return answer

    def _extract_search_params(self, text: str) -> Dict[str, Any]:
        dates = self._extract_dates(text)
        
        # Determine nights to carry over
        prev_nights = None
        last_results = self.toolset.last_filtered_results or self.toolset.last_search_results
        if last_results:
            prev_nights = last_results[0].get("nights")
            
        if len(dates) >= 2:
            check_in, check_out = dates[0], dates[1]
        elif len(dates) == 1:
            check_in_date = date.fromisoformat(dates[0])
            check_in = check_in_date.isoformat()
            nights = prev_nights if prev_nights is not None else 1
            check_out = (check_in_date + timedelta(days=nights)).isoformat()
        else:
            today = date(2026, 6, 1) # Set baseline date as per metadata
            days_until_friday = (4 - today.weekday()) % 7 or 7
            check_in_date = today + timedelta(days=days_until_friday)
            check_in = check_in_date.isoformat()
            nights = prev_nights if prev_nights is not None else 2
            check_out = (check_in_date + timedelta(days=nights)).isoformat()

        adults = self._extract_count(text, ["nguoi lon", "adult", "adults"])
        if adults is None:
            adults = self._extract_count(text, ["nguoi", "khach", "pax", "guest", "guests"])
        if adults is None:
            adults = 2
            
        children = self._extract_count(text, ["tre em", "tre", "child", "children"]) or 0
        return {
            "location": "Nha Trang",
            "check_in": check_in,
            "check_out": check_out,
            "adults": adults,
            "children": children,
        }

    def _extract_dates(self, text: str) -> List[str]:
        # 1. Match YYYY-MM-DD
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
        
        # 2. Match DD/MM/YYYY or DD-MM-YYYY
        for day, month, year in re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text):
            try:
                parsed = date(int(year), int(month), int(day)).isoformat()
                if parsed not in dates:
                    dates.append(parsed)
            except ValueError:
                pass
                
        # 3. Match DD/MM or DD-MM (using 2026 as default year)
        for match in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})\b", text):
            day_str, month_str = match.group(1), match.group(2)
            end_pos = match.end()
            if end_pos < len(text) and text[end_pos] in "/-":
                after_text = text[end_pos+1:]
                year_match = re.match(r"^\d{2,4}", after_text)
                if year_match:
                    continue
            try:
                parsed = date(2026, int(month_str), int(day_str)).isoformat()
                if parsed not in dates:
                    dates.append(parsed)
            except ValueError:
                pass
                
        return dates

    def _extract_max_price(self, text: str) -> Optional[int]:
        normalized = _normalize(text)
        if not any(keyword in normalized for keyword in ["duoi", "toi da", "khong qua", "<=", "nho hon"]):
            return None

        million_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:trieu|million)", normalized)
        if million_match:
            return normalize_max_price(int(float(million_match.group(1).replace(",", ".")) * 1_000_000))

        money_match = re.search(r"(\d[\d.,]{5,})\s*(?:vnd|dong|d)?", normalized)
        if money_match:
            digits = re.sub(r"\D", "", money_match.group(1))
            return normalize_max_price(int(digits)) if digits else None
        return None

    def _extract_count(self, text: str, labels: List[str]) -> Optional[int]:
        normalized = _normalize(text)
        for label in labels:
            match = re.search(rf"(\d+)\s*{re.escape(_normalize(label))}", normalized)
            if match:
                return int(match.group(1))
        return None

    def _extract_package_code(self, text: str) -> Optional[str]:
        matches = re.findall(r"\b([A-Z0-9]+(?:-[A-Z0-9]+)+)\b", text.upper())
        return matches[0] if matches else None

    def _extract_guest_name(self, text: str) -> Optional[str]:
        match = re.search(r"\bcho\s+(.+)$", text, re.IGNORECASE)
        if not match:
            return None
        name = match.group(1).strip()
        return name if name else None

    def _has_confirmation(self, normalized: str) -> bool:
        return any(keyword in normalized for keyword in CONFIRM_KEYWORDS)

    def _nights(self, check_in: str, check_out: str) -> int:
        start = date.fromisoformat(check_in)
        end = date.fromisoformat(check_out)
        return max((end - start).days, 1)


class ExtractionBasedVinpearlAgent(RuleBasedVinpearlAgent):
    """
    A single-turn Structured Extraction Agent that uses the LLM to parse
    the user input into a JSON schema, then executes the corresponding
    tools deterministically using Python code.
    """

    def __init__(self, toolset: VinpearlToolset, llm: LLMProvider):
        super().__init__(toolset)
        self.llm = llm

    def get_system_prompt(self) -> str:
        return """You are a hotel booking assistant for Vinpearl Nha Trang. Your task is to analyze the user's message and extract parameters into a JSON object.

Output JSON schema:
{
  "intent": "search" | "book" | "confirm" | "greeting" | "unrelated",
  "location": "Nha Trang" or null,
  "check_in": "YYYY-MM-DD" or null (extract check-in date mentioned in the user's current message, e.g. "ngay 5/6" -> "2026-06-05"),
  "check_out": "YYYY-MM-DD" or null (ONLY extract if checkout date or stay nights is explicitly mentioned in user's current message. Otherwise set to null),
  "adults": int or null (number of adult guests. E.g. "cho 6 nguoi" -> 6. Default to null if not specified),
  "children": int or null (number of children guests. Default to null if not specified),
  "max_price": int or null (budget ceiling in VND, e.g. 10000000 for 10 million/10 triệu. Default to null if not specified),
  "includes": list of strings (e.g. ["VinWonders"], default to empty list []),
  "package_code": "Package code like FAM-SUITE-VW" or null,
  "guest_name": "Guest name" or null
}

Rules:
1. ONLY return the valid JSON string. Do not include any explanations, markdown code blocks, or HTML.
2. If the user is asking to find rooms (e.g. "tìm phòng", "tìm phòng cho 6 người"), set intent to "search". Do NOT set to "book" unless they explicitly want to make a temporary booking/reservation (e.g. "đặt tạm", "đặt phòng", "giữ chỗ").
3. Do not perform date calculations. Extract check_in and check_out ONLY if they are explicitly mentioned. Set check_out to null unless checkout date or stay nights is explicitly mentioned.
4. Do not carry over dates or counts into the JSON fields from the conversation history if they are overridden or not mentioned. Focus on the current user input, using history only for context.
"""

    def run(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        
        # Build history context (last 3 turns)
        history_context = ""
        if self.history:
            history_context = "Conversation history:\n"
            for msg in self.history[-6:-1]:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_context += f"{role}: {msg['content']}\n"
            history_context += "\n"
            
        current_date_info = f"\nNote: Current local date is 2026-06-01 (Monday)."
        prompt = f"{history_context}Current User input: {user_input}{current_date_info}\nExtract JSON based on the context of the conversation:"
        
        result = self.llm.generate(prompt, system_prompt=self.get_system_prompt())
        content = result.get("content", "").strip()
        
        # Robust JSON extraction
        match = re.search(r"(\{.*\})", content, re.DOTALL)
        if match:
            content = match.group(1)
        elif content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        try:
            data = json.loads(content)
        except Exception:
            # Fallback to rule-based agent if JSON parsing fails
            fallback = RuleBasedVinpearlAgent(self.toolset)
            fallback.history = list(self.history)
            return fallback.run(user_input)
            
        intent = data.get("intent", "unrelated")
        
        if intent == "greeting":
            return "Chào bạn! Tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Bạn cần hỗ trợ tìm phòng hay đặt phòng cho thời gian nào ạ?"
            
        if intent == "unrelated":
            return "Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Tôi không thể trả lời các câu hỏi ngoài phạm vi này."
            
        if intent == "confirm":
            if self.toolset.pending_booking:
                booking_id = self.toolset.pending_booking["booking_id"]
                return self.toolset.confirm_booking(booking_id, user_input)
            return "Không có booking tạm nào đang chờ xác nhận."
            
        if intent == "book":
            package_code = data.get("package_code")
            if not package_code:
                package_code = self._extract_package_code(user_input)
            if not package_code:
                return "Vui lòng cung cấp mã gói phòng để tiến hành giữ chỗ."
                
            def is_valid_date(val: Any) -> bool:
                if not isinstance(val, str):
                    return False
                try:
                    date.fromisoformat(val)
                    return True
                except ValueError:
                    return False
                    
            check_in = data.get("check_in")
            check_out = data.get("check_out")
            if not is_valid_date(check_in):
                check_in = None
            if not is_valid_date(check_out):
                check_out = None
                
            if not check_in or not check_out:
                # Fallback to extraction from text if JSON extraction missed dates
                dates = self._extract_dates(user_input)
                if len(dates) >= 2:
                    check_in, check_out = dates[0], dates[1]
                elif len(dates) == 1:
                    check_in_date = date.fromisoformat(dates[0])
                    check_in = check_in_date.isoformat()
                    check_out = (check_in_date + timedelta(days=1)).isoformat()
                    
            guest_name = data.get("guest_name") or self._extract_guest_name(user_input) or "Khach Vinpearl"
            return self.toolset.prepare_booking(
                package_code=package_code,
                guest_name=guest_name,
                check_in=check_in,
                check_out=check_out
            )
            
        # Default to search
        check_in = data.get("check_in")
        check_out = data.get("check_out")
        
        # Validate date format, if invalid, reset to None to use Python parsing fallback
        def is_valid_date(val: Any) -> bool:
            if not isinstance(val, str):
                return False
            try:
                date.fromisoformat(val)
                return True
            except ValueError:
                return False
                
        if not is_valid_date(check_in):
            check_in = None
        if not is_valid_date(check_out):
            check_out = None
            
        # Fallback parsing if LLM missed dates
        if not check_in or not check_out:
            dates = self._extract_dates(user_input)
            
            # Determine nights to carry over
            prev_nights = None
            last_results = self.toolset.last_filtered_results or self.toolset.last_search_results
            if last_results:
                prev_nights = last_results[0].get("nights")
                
            if len(dates) >= 2:
                check_in, check_out = dates[0], dates[1]
            elif len(dates) == 1:
                check_in_date = date.fromisoformat(dates[0])
                check_in = check_in_date.isoformat()
                nights = prev_nights if prev_nights is not None else 1
                check_out = (check_in_date + timedelta(days=nights)).isoformat()
            else:
                today = date(2026, 6, 1) # Set baseline date as per metadata
                days_until_friday = (4 - today.weekday()) % 7 or 7
                check_in_date = today + timedelta(days=days_until_friday)
                check_in = check_in_date.isoformat()
                nights = prev_nights if prev_nights is not None else 2
                check_out = (check_in_date + timedelta(days=nights)).isoformat()
                
        adults = data.get("adults")
        if adults is None:
            adults = self._extract_count(user_input, ["nguoi lon", "adult", "adults"])
        if adults is None:
            adults = self._extract_count(user_input, ["nguoi", "khach", "pax", "guest", "guests"])
        if adults is None:
            adults = 2
            
        children = data.get("children")
        if children is None:
            children = self._extract_count(user_input, ["tre em", "tre", "child", "children"])
        if children is None:
            children = 0
        
        # Update persistent filters
        max_price = data.get("max_price")
        if max_price is not None:
            max_price = normalize_max_price(max_price)
            self.toolset.last_max_price = max_price
        elif any(phrase in _normalize(user_input) for phrase in ["khong gioi han gia", "gia nao cung duoc", "bo loc gia", "bo gia"]):
            self.toolset.last_max_price = None
            
        includes = data.get("includes") or []
        if "vinwonders" in _normalize(user_input) and "VinWonders" not in includes:
            includes.append("VinWonders")
        if includes:
            for item in includes:
                if item not in self.toolset.last_includes:
                    self.toolset.last_includes.append(item)
                    
        observation = self.toolset.search_vinpearl_packages(
            location=data.get("location") or "Nha Trang",
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children
        )
        
        effective_max_price = self.toolset.last_max_price
        effective_includes = self.toolset.last_includes
        
        if effective_includes or effective_max_price is not None:
            observation = self.toolset.filter_packages(includes=effective_includes, max_price=effective_max_price)
            
        # Convert output to proper accented Vietnamese
        observation_clean = observation.replace("Cac lua chon phu hop:", "Các lựa chọn phù hợp:")
        observation_clean = observation_clean.replace("Lua chon sau khi loc:", "Lựa chọn sau khi lọc:")
        
        answer = (
            f"{observation_clean}\n\n"
            "Nếu muốn giữ chỗ, hãy nhấn: dat tam <ma goi> cho <ten khach>. "
            "Tôi chỉ xác nhận đặt khi bạn nói rõ 'xác nhận đặt' hoặc 'chốt đặt'."
        )
        self.history.append({"role": "assistant", "content": answer})
        return answer


class VinpearlChatAgent:
    """
    Chat wrapper that uses LocalProvider/ReAct when a model is present, with a
    deterministic fallback for development and UI testing.
    """

    def __init__(self, toolset: VinpearlToolset, llm: Optional[LLMProvider] = None, agent_type: str = "extraction"):
        self.toolset = toolset
        self.mode = "local-model" if llm else "rule-based"
        if not llm:
            self.agent = RuleBasedVinpearlAgent(toolset)
        elif agent_type == "react":
            self.agent = ReActAgent(llm=llm, tools=toolset.as_tools(), max_steps=6)
        else:
            self.agent = ExtractionBasedVinpearlAgent(toolset, llm)

    def run(self, user_input: str) -> str:
        # 1. Check for greeting first
        if _is_pure_greeting(user_input):
            return "Chào bạn! Tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Bạn cần hỗ trợ tìm phòng hay đặt phòng cho thời gian nào ạ?"

        # 2. Check for specific lookup query (price or package code info)
        if isinstance(self.agent, RuleBasedVinpearlAgent):
            lookup_answer = self.agent._handle_lookup(user_input)
            if lookup_answer:
                return lookup_answer
        else:
            temp_rule_agent = RuleBasedVinpearlAgent(self.toolset)
            lookup_answer = temp_rule_agent._handle_lookup(user_input)
            if lookup_answer:
                return lookup_answer

        # 3. Check for relevance
        has_pending = self.toolset.pending_booking is not None
        if not _is_relevant(user_input, pending_booking=has_pending):
            return "Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Tôi không thể trả lời các câu hỏi ngoài phạm vi này."

        return self.agent.run(user_input)
