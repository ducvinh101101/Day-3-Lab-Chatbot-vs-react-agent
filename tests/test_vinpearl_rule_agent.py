from src.agent.vinpearl_booking_agent import RuleBasedVinpearlAgent, VinpearlChatAgent
from src.tools.vinpearl_tools import VinpearlToolset


def test_rule_agent_parses_slash_date_and_price_ceiling():
    agent = RuleBasedVinpearlAgent(VinpearlToolset())

    answer = agent.run("Tim phong duoi 6 trieu cho toi ngay 6/6/2026")

    assert "DLX-SEAVIEW-BB" in answer
    assert "4.800.000 VND" in answer
    assert "FAM-SUITE-VW" not in answer
    assert "2 dem" not in answer


def test_rule_agent_greetings_and_out_of_scope():
    agent = RuleBasedVinpearlAgent(VinpearlToolset())

    # Test short pure greetings
    greetings = ["hello", "hi", "chào bạn", "Xin chào"]
    for greeting in greetings:
        res = agent.run(greeting)
        assert "Tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang" in res
        assert "Bạn cần hỗ trợ tìm phòng hay đặt phòng" in res

    # Test out of scope queries
    unrelated = ["Thời tiết hôm nay thế nào?", "Hà Nội có bao nhiêu quận?", "Lịch sử của Nha Trang", "what is machine learning"]
    for query in unrelated:
        res = agent.run(query)
        assert "Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng tại Vinpearl Nha Trang. Tôi không thể trả lời các câu hỏi ngoài phạm vi này." in res


def test_rule_agent_specific_lookups():
    toolset = VinpearlToolset()
    agent = RuleBasedVinpearlAgent(toolset)

    # Search first to populate last_search_results
    agent.run("Tim phong cho 2 nguoi lon, 2 tre em")

    # Look up by price (from the populated search results)
    res_price = agent.run("Phòng 28.400.000 VND là phòng nào")
    assert "VILLA-3BR-VW" in res_price
    assert "Villa 3 phòng ngủ" in res_price

    # Look up by room code
    res_code = agent.run("gói FAM-SUITE-VW gồm những gì")
    assert "Family Suite" in res_code
    assert "VinWonders" in res_code


def test_chat_agent_global_guardrails():
    # Verify VinpearlChatAgent also applies these checks globally
    chat_agent = VinpearlChatAgent(VinpearlToolset())

    res_greeting = chat_agent.run("hi")
    assert "Tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng" in res_greeting

    res_unrelated = chat_agent.run("Thời tiết thế nào?")
    assert "Xin lỗi, tôi là trợ lý ảo chuyên hỗ trợ tìm phòng và đặt phòng" in res_unrelated


def test_rule_agent_parses_general_people_count():
    agent = RuleBasedVinpearlAgent(VinpearlToolset())
    answer = agent.run("tôi cần tìm phòng cho 6 người giá dưới 10 triệu")
    # DLX-SEAVIEW-BB (capacity 2 adults) should not match since it's for 6 people
    assert "DLX-SEAVIEW-BB" not in answer
    # VILLA-3BR-VW matches the capacity of 6 adults, but is > 10M, so results should be empty
    assert "Không có lựa chọn nào đáp ứng tất cả tiêu chí lọc." in answer

