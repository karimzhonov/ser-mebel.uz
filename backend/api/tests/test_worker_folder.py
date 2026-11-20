"""«👷 Ishchi kartasi» → the worker's own folder: personal data (pasport, prava, ish
staji), files kept in the DB and the month-by-month salary history."""

import io
from datetime import date

import pytest

from accounting import salary as SAL
from accounting import services as S
from accounting import workers as WK
from accounting.models import Worker, WorkerFile
from accounting.text import add_months, cur_month

BASE = "/api/v1/finance/workers"
PDF = b"%PDF-1.4 fake"


def upload(client, w, *, kind="salary", month="2025-03", name="oylik.pdf", content=PDF, **extra):
    f = io.BytesIO(content)
    f.name = name
    data = {"file": f, "kind": kind, **extra}
    if month:
        data["month"] = month
    return client.post(f"{BASE}/{w.pk}/files/", data, format="multipart")


@pytest.fixture
def worker(members):
    w = Worker.objects.create(group="Sex", name="Akmal", position="Usta")
    boss = members[0]
    for d, amount, pay_type in [
        (date(2026, 9, 10), 300_000, "Avans"),
        (date(2026, 9, 30), 2_000_000, "Oylik"),
        (date(2026, 10, 12), 400_000, "Avans"),
    ]:
        S.create_operation(
            member=boss,
            kind="expense",
            amount=amount,
            category_code="oylik",
            worker="akmal ",
            pay_type=pay_type,
            on_date=d,
            actor_admin=True,
        )
    return w


def test_profile_read_and_update(admin_api, worker):
    r = admin_api.get(f"{BASE}/{worker.pk}/profile/")
    assert r.status_code == 200
    assert r.data["passport_number"] == "" and r.data["experience"]["total"] == 0
    r = admin_api.patch(
        f"{BASE}/{worker.pk}/profile/",
        {
            "passport_number": "aa1234567",
            "pinfl": "123 456 789 012 34",
            "passport_issued_on": "2020-01-15",
            "license_number": "af 7654321",
            "license_categories": "b,c  e",
            "license_expires": "2030-05-01",
            "hired_on": "2023-01-10",
            "prior_experience_months": 30,
            "experience_note": "  Mebel-X  ",
            "phone": "+998901234567",
        },
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["passport_number"] == "AA 1234567"
    assert r.data["pinfl"] == "12345678901234"
    assert r.data["license_number"] == "AF 7654321"
    assert r.data["license_categories"] == "B, C, E"
    assert r.data["experience_note"] == "Mebel-X"
    exp = r.data["experience"]
    assert exp["prior"] == 30 and exp["here"] >= 46 and exp["total"] == exp["here"] + 30
    worker.refresh_from_db()
    assert worker.hired_on == date(2023, 1, 10)


def test_profile_validation(admin_api, worker):
    r = admin_api.patch(f"{BASE}/{worker.pk}/profile/", {"pinfl": "123"}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "pinfl"
    r = admin_api.patch(f"{BASE}/{worker.pk}/profile/", {"hired_on": "2999-01-01"}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "hired_on"
    r = admin_api.patch(f"{BASE}/{worker.pk}/profile/", {"birth_date": "nope"}, format="json")
    assert r.status_code == 400 and "birth_date" in r.data


def test_personal_data_never_in_the_plain_list(api, worker):
    worker.passport_number = "AA 1234567"
    worker.save()
    viewer = api("accounting.view_worker")
    r = viewer.get(f"{BASE}/")
    assert r.status_code == 200 and "passport_number" not in r.data[0]
    assert viewer.get(f"{BASE}/{worker.pk}/profile/").status_code == 403
    assert viewer.get(f"{BASE}/{worker.pk}/files/").status_code == 403
    assert viewer.get(f"{BASE}/{worker.pk}/months/").status_code == 403


def test_permissions_read_vs_write(api, worker):
    reader = api("accounting.view_worker", "accounting.view_all_operations")
    assert reader.get(f"{BASE}/{worker.pk}/profile/").status_code == 200
    assert (
        reader.patch(f"{BASE}/{worker.pk}/profile/", {"phone": "1"}, format="json").status_code
        == 403
    )
    assert upload(reader, worker).status_code == 403
    f = WK.save_file(worker, kind="passport", name="p.jpg", content=b"jpg")
    assert reader.get(f"{BASE}/{worker.pk}/files/{f.pk}/").status_code == 200
    assert reader.delete(f"{BASE}/{worker.pk}/files/{f.pk}/").status_code == 403
    # change_worker alone does not open company pay / personal data
    editor = api("accounting.view_worker", "accounting.change_worker")
    assert editor.get(f"{BASE}/{worker.pk}/profile/").status_code == 403
    assert upload(editor, worker).status_code == 403
    both = api(
        "accounting.view_worker", "accounting.view_all_operations", "accounting.change_worker"
    )
    assert upload(both, worker).status_code == 201
    assert both.delete(f"{BASE}/{worker.pk}/files/{f.pk}/").status_code == 204


def test_upload_download_delete(admin_api, worker):
    r = upload(admin_api, worker, kind="passport", month="", name="pasport.jpg", content=b"img")
    assert r.status_code == 201, r.data
    assert r.data["kind"] == "passport" and r.data["month"] is None
    assert r.data["content_type"] == "image/jpeg" and r.data["size"] == 3
    fid = r.data["id"]
    r = admin_api.get(f"{BASE}/{worker.pk}/files/")
    assert [x["id"] for x in r.data] == [fid] and "data" not in r.data[0]
    r = admin_api.get(f"{BASE}/{worker.pk}/files/{fid}/")
    assert r.status_code == 200 and r.content == b"img"
    assert r["Content-Type"] == "image/jpeg"
    assert r["Content-Disposition"].startswith('attachment; filename="pasport.jpg"')
    # another worker's file is not reachable through this worker
    other = Worker.objects.create(group="Sex", name="Bobur")
    assert admin_api.get(f"{BASE}/{other.pk}/files/{fid}/").status_code == 404
    assert admin_api.delete(f"{BASE}/{worker.pk}/files/{fid}/").status_code == 204
    assert not WorkerFile.objects.exists()


def test_upload_refusals(admin_api, worker):
    assert upload(admin_api, worker, name="x.html", content=b"<script>").status_code == 400
    assert upload(admin_api, worker, name="x.svg").status_code == 400
    assert upload(admin_api, worker, content=b"").status_code == 400
    assert upload(admin_api, worker, kind="bad").status_code == 400
    # a salary sheet needs its month, and never a future one
    r = upload(admin_api, worker, month="")
    assert r.status_code == 400 and r.data.get("field") == "month"
    r = upload(admin_api, worker, month=add_months(cur_month(), 1))
    assert r.status_code == 400 and r.data.get("field") == "month"
    assert upload(admin_api, worker, month=cur_month()).status_code == 201


def test_too_big(admin_api, worker, monkeypatch):
    monkeypatch.setattr(WK, "MAX_FILE", 10)
    assert upload(admin_api, worker, content=b"x" * 11).status_code == 400


def test_months_history_with_past_sheets(admin_api, worker):
    # a sheet for a month long before the bot, and one for a paid month
    assert upload(admin_api, worker, month="2024-12", name="dekabr.xlsx").status_code == 201
    assert upload(admin_api, worker, month="2026-09-15", name="sentabr.pdf").status_code == 201
    # passport scans never show up as a month
    upload(admin_api, worker, kind="passport", month="2026-08", name="p.png")
    r = admin_api.get(f"{BASE}/{worker.pk}/months/")
    assert r.status_code == 200
    assert [m["month"] for m in r.data] == ["2026-10", "2026-09", "2024-12"]
    oct_, sep, dec = r.data
    assert (oct_["advance"], oct_["salary"], oct_["total"], oct_["count"]) == (
        400_000,
        0,
        400_000,
        1,
    )
    assert (sep["advance"], sep["salary"], sep["total"]) == (300_000, 2_000_000, 2_300_000)
    assert [f["name"] for f in sep["files"]] == ["sentabr.pdf"]
    assert sep["files"][0]["month"] == "2026-09"
    assert dec["total"] == 0 and [f["name"] for f in dec["files"]] == ["dekabr.xlsx"]


def test_months_between():
    assert WK.months_between(date(2023, 1, 10), date(2023, 2, 9)) == 0
    assert WK.months_between(date(2023, 1, 10), date(2023, 2, 10)) == 1
    assert WK.months_between(date(2023, 1, 31), date(2024, 1, 30)) == 11
    assert WK.months_between(date(2024, 1, 1), date(2023, 1, 1)) == 0


def test_months_follow_the_pay_day(admin_api, worker):
    """With a pay day the month is the salary period of «Oylik chiqarish»: an advance
    after the 5th counts for next month, and that month's sheet may be uploaded now."""
    worker.pay_day = 5
    worker.save()
    assert WK.salary_month_of(worker, date(2026, 9, 5)) == "2026-09"
    assert WK.salary_month_of(worker, date(2026, 9, 6)) == "2026-10"
    r = admin_api.get(f"{BASE}/{worker.pk}/months/")
    # 10 Sep + 30 Sep → October's salary, 12 Oct → November's
    assert [m["month"] for m in r.data] == ["2026-11", "2026-10"]
    assert r.data[1]["advance"] == 300_000 and r.data[1]["salary"] == 2_000_000
    nxt = SAL.next_month(worker)
    assert upload(admin_api, worker, month=nxt).status_code == 201
    assert upload(admin_api, worker, month=add_months(nxt, 1)).status_code == 400


def test_months_only_this_worker(admin_api, worker, members):
    S.create_operation(
        member=members[0],
        kind="expense",
        amount=777,
        category_code="oylik",
        worker="Akmalov",
        pay_type="Avans",
        on_date=date(2026, 10, 1),
        actor_admin=True,
    )
    r = admin_api.get(f"{BASE}/{worker.pk}/months/")
    assert sum(m["total"] for m in r.data) == 2_700_000


def test_worker_with_files_is_not_deleted(admin_api, worker):
    upload(admin_api, worker, kind="passport", month="", name="p.jpg")
    r = admin_api.delete(f"{BASE}/{worker.pk}/")
    assert r.status_code == 400 and Worker.objects.filter(pk=worker.pk).exists()
    WorkerFile.objects.all().delete()
    assert admin_api.delete(f"{BASE}/{worker.pk}/").status_code == 204


def test_cleanup_never_overflows_and_names_are_clean(admin_api, worker):
    r = admin_api.patch(
        f"{BASE}/{worker.pk}/profile/",
        {"license_categories": "A B C D E F G H I J K L M N O P"},
        format="json",
    )
    assert r.status_code == 400 and r.data.get("field") == "license_categories"
    assert admin_api.patch(f"{BASE}/{worker.pk}/profile/", {}, format="json").status_code == 200
    f = WK.save_file(worker, kind="other", name='bad\r\nname";.pdf', content=PDF)
    assert f.name == 'bad name";.pdf'
    r = admin_api.get(f"{BASE}/{worker.pk}/files/{f.pk}/")
    assert r.status_code == 200
    plain = r["Content-Disposition"].split("; filename*=")[0]
    assert plain.count('"') == 2 and ";" not in plain.removeprefix("attachment;")
