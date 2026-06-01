import json
import shutil

from src.tools.vinpearl_tools import DATA_PATH, VinpearlToolset


def make_toolset(tmp_path):
    data_path = tmp_path / "inventory.json"
    shutil.copyfile(DATA_PATH, data_path)
    return VinpearlToolset(data_path=str(data_path)), data_path


def test_confirm_booking_requires_explicit_user_confirmation(tmp_path):
    toolset, _ = make_toolset(tmp_path)
    toolset.search_vinpearl_packages(
        location="Nha Trang",
        check_in="2026-06-05",
        check_out="2026-06-07",
        adults=2,
        children=2,
    )
    toolset.filter_packages(includes=["VinWonders"])
    pending = toolset.prepare_booking(
        package_code="FAM-SUITE-VW",
        guest_name="Nguyen Van A",
    )

    booking_id = toolset.pending_booking["booking_id"]
    blocked = toolset.confirm_booking(booking_id=booking_id, user_message="cho toi xem lai thong tin")
    confirmed = toolset.confirm_booking(booking_id=booking_id, user_message="toi xac nhan dat")

    assert "Đã tạo booking tạm" in pending
    assert "Không xác nhận booking" in blocked
    assert "Xác nhận thành công" in confirmed
    assert toolset.pending_booking is None
    assert len(toolset.confirmed_bookings) == 1


def test_confirm_booking_updates_inventory_and_sold_out_message(tmp_path):
    toolset, data_path = make_toolset(tmp_path)
    toolset.search_vinpearl_packages(
        location="Nha Trang",
        check_in="2026-06-05",
        check_out="2026-06-07",
        adults=4,
        children=2,
    )
    pending = toolset.prepare_booking(
        package_code="VILLA-2BR-FB-VW",
        guest_name="Nguyen Van B",
    )
    booking_id = toolset.pending_booking["booking_id"]
    confirmed = toolset.confirm_booking(booking_id=booking_id, user_message="toi xac nhan dat")

    with open(data_path, "r", encoding="utf-8") as file:
        inventory = json.load(file)

    villa = inventory["resorts"][1]["rooms"][0]
    second_search = toolset.search_vinpearl_packages(
        location="Nha Trang",
        check_in="2026-06-05",
        check_out="2026-06-07",
        adults=4,
        children=2,
    )

    assert "Đã tạo booking tạm" in pending
    assert "Xác nhận thành công" in confirmed
    assert villa["status_by_date"]["2026-06-05"]["available"] == 0
    assert villa["status_by_date"]["2026-06-06"]["available"] == 0
    assert villa["status_by_date"]["2026-06-05"]["status"] == "sold_out"
    assert "VILLA-2BR-FB-VW" not in second_search
