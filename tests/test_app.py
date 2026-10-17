"""Функциональные тесты интерфейса через streamlit.testing (реальный прогон app.py, v1.2)."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
T = date(2026, 10, 17)


def d(n):
    return T + timedelta(days=n)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("KONTUR_DATA", str(tmp_path / "state.json"))
    monkeypatch.setenv("KONTUR_TODAY", T.isoformat())
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    at.data_path = tmp_path / "state.json"
    return at


def go(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    return at


def card(at, oid):
    go(at, "Карточка заказа")
    at.selectbox(key="selected_id").set_value(oid).run()
    assert not at.exception, at.exception
    return at


def metric(at, label):
    return next(m for m in at.metric if m.label == label).value


def saved(at):
    data = json.loads(at.data_path.read_text(encoding="utf-8"))
    return data, {o["id"]: o for o in data["orders"]}


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception


def errors(at):
    return " ".join(e.value for e in at.error)


def set_dev(at, prefix, reason, origin, comment):
    at.selectbox(key=f"{prefix}_reason").set_value(reason)
    at.selectbox(key=f"{prefix}_origin").set_value(origin)
    at.text_input(key=f"{prefix}_comment").set_value(comment)


def test_every_page_and_card_renders(app):
    for page in ["Требуют вмешательства", "Панель руководителя", "Реестр заказов",
                 "Карточка заказа", "Журнал изменений", "Правила"]:
        go(app, page)
    for oid in ["KZ-26-105", "KZ-26-107", "KZ-26-111", "KZ-26-124-R1"]:
        card(app, oid)
    assert any("Синтетические" in w.value for w in app.sidebar.warning)


def test_excluded_features_not_shown(app):
    labels = [b.label for b in app.button] + [b.label for b in app.get("download_button")]
    go(app, "Панель руководителя")
    labels += [b.label for b in app.button]
    assert not any("CSV" in x for x in labels)
    go(app, "Правила")
    assert not app.number_input  # настроек порогов в интерфейсе нет
    assert len(app.sidebar.multiselect) == 2  # только ответственный и канал


def test_attention_list_shows_executor_and_order(app):
    subs = [s.value for s in app.subheader]
    assert subs[:3] == ["Просрочены — 2", "Заблокированы — 1", "Под риском — 7"]
    text = " ".join(m.value for m in app.markdown)
    assert text.index("KZ-26-102") < text.index("KZ-26-114") < text.index("KZ-26-104")
    assert "Яковлева Т. (снабжение)" in text  # исполнитель ≠ ответственный за стадию (KZ-26-104)
    assert "KZ-26-101" not in text and "KZ-26-111" not in text


def test_dashboard_values_and_denominators(app):
    go(app, "Панель руководителя")
    assert metric(app, "Активных заказов") == "19"
    assert metric(app, "Просрочено") == "2"
    assert metric(app, "Закрыто с нарушением срока") == "1"
    assert metric(app, "Срывы с подтверждённой причиной") == "1"
    assert metric(app, "Первоначальный срок сверен") == "16"
    captions = " ".join(c.value for c in app.caption)
    assert "из 17 · 12 %" in captions and "из 3 · 33 %" in captions and "из 5 · 20 %" in captions
    assert "из 17 · 94 %" in captions and "исключено (срок не сверен): 1" in captions
    # Таблица ищется по составу колонок, а не по месту на странице: вёрстка панели меняется.
    margin = next(d.value for d in app.dataframe if "Канал" in d.value.columns)
    dealer = margin[margin["Канал"] == "Дилер"].iloc[0]
    assert dealer["Порог канала"] == "15 %" and dealer["Ниже порога"] == 1


def test_filter_by_executor_and_channel(app):
    go(app, "Требуют вмешательства")
    app.sidebar.multiselect[0].set_value(["Яковлева Т. (снабжение)"]).run()
    text = " ".join(m.value for m in app.markdown)
    assert "KZ-26-104" in text and "KZ-26-102" not in text
    app.sidebar.multiselect[0].set_value([]).run()
    go(app, "Панель руководителя")
    app.sidebar.multiselect[1].set_value(["dealer"]).run()
    assert metric(app, "Активных заказов") == "9"


def test_main_scenario_deadline_move_requires_deviation(app):
    card(app, "KZ-26-102")
    app.date_input(key="planned_KZ-26-102").set_value(d(10))
    click(app, "Сохранить")
    assert "Перенос планового срока требует отклонения" in errors(app)
    _, orders = saved(app)
    assert orders["KZ-26-102"]["planned_completion"] == d(-4).isoformat()

    app.date_input(key="planned_KZ-26-102").set_value(d(10))
    set_dev(app, "opsdev_KZ-26-102", "measure_error", 1, "Согласован новый срок с дилером после перезамера")
    click(app, "Сохранить")
    assert not app.error, errors(app)
    data, orders = saved(app)
    o = orders["KZ-26-102"]
    assert o["planned_completion"] == d(10).isoformat()
    assert o["baseline_completion"] == d(-4).isoformat()
    assert o["deviations"][-1]["trigger"] == "deadline_move" and len(o["deviations"]) == 3
    assert any(e["field"] == "deviation" and e["order_id"] == "KZ-26-102" and e["user"] != "демо-история"
               for e in data["audit"])
    go(app, "Панель руководителя")
    assert metric(app, "Просрочено") == "1"


def test_block_requires_deviation_and_executor(app):
    card(app, "KZ-26-101")
    app.checkbox(key="blocked_KZ-26-101").check()
    click(app, "Сохранить")
    assert "Блокировка требует отклонения" in errors(app)
    app.checkbox(key="blocked_KZ-26-101").check()
    app.text_input(key="next_KZ-26-101").set_value("Привезти ЛДСП от второго поставщика")
    app.selectbox(key="executor_KZ-26-101").set_value("Яковлева Т. (снабжение)")
    set_dev(app, "opsdev_KZ-26-101", "material_shortage", 3, "Нет ЛДСП нужного декора")
    click(app, "Сохранить")
    assert not app.error, errors(app)
    _, orders = saved(app)
    o = orders["KZ-26-101"]
    assert o["is_blocked"] and o["block_deviation_id"] == "KZ-26-101-D1"
    assert o["next_action_owner"] == "Яковлева Т. (снабжение)"


def test_stage_skip_allowed_back_requires_deviation(app):
    card(app, "KZ-26-110")
    app.selectbox(key="stage_KZ-26-110").set_value(3)
    app.text_input(key="next_KZ-26-110").set_value("Деталировка по готовому проекту дилера")
    app.selectbox(key="owner_KZ-26-110").set_value("Зуев М. (технолог)")
    app.selectbox(key="executor_KZ-26-110").set_value("Зуев М. (технолог)")
    click(app, "Сохранить")
    assert not app.error, errors(app)
    _, orders = saved(app)
    assert [v["stage"] for v in orders["KZ-26-110"]["stage_history"]] == [1, 3]

    card(app, "KZ-26-110")
    app.selectbox(key="stage_KZ-26-110").set_value(1)
    app.text_input(key="next_KZ-26-110").set_value("Перезамер")
    click(app, "Сохранить")
    assert "Возврат на предыдущую стадию требует отклонения" in errors(app)


def test_contract_signing_and_baseline_verification(app):
    card(app, "KZ-26-123")
    app.date_input(key="deadline_KZ-26-123").set_value(d(50))
    click(app, "Подписан договор")
    assert not app.error, errors(app)
    _, orders = saved(app)
    o = orders["KZ-26-123"]
    assert o["contract_date"] == T.isoformat() and o["baseline_completion"] == d(50).isoformat()
    assert o["baseline_verified"] is True

    card(app, "KZ-26-107")
    app.date_input(key="base_KZ-26-107").set_value(d(25))
    click(app, "Сверено с договором")
    assert not app.error, errors(app)
    _, orders = saved(app)
    assert orders["KZ-26-107"]["baseline_verified"] and orders["KZ-26-107"]["baseline_completion"] == d(25).isoformat()
    card(app, "KZ-26-107")
    assert not [b for b in app.button if b.label == "Сверено с договором"]


def test_finance_edit_does_not_refresh_status(app):
    card(app, "KZ-26-107")
    app.number_input(key="cp2_KZ-26-107").set_value(390_000.0)
    click(app, "Сохранить экономику")
    _, orders = saved(app)
    assert orders["KZ-26-107"]["contract_price"] == 390_000.0
    assert orders["KZ-26-107"]["status_updated_at"] == d(-16).isoformat()


def test_confirm_deviation_raises_explained_share(app):
    card(app, "KZ-26-102")
    click(app, "Подтвердить")  # последнее отклонение заказа (D2) — первое в списке
    _, orders = saved(app)
    assert orders["KZ-26-102"]["deviations"][1]["confirmed"] is True
    go(app, "Панель руководителя")
    assert metric(app, "Срывы с подтверждённой причиной") == "2"


def test_complaint_creation(app):
    card(app, "KZ-26-111")
    click(app, "Оформить рекламацию")
    assert "Отклонение: выберите причину" in errors(app)
    set_dev(app, "cdev_KZ-26-111", "product_defect", 4, "Скол на столешнице")
    app.date_input(key="cdeadline_KZ-26-111").set_value(d(14))
    app.selectbox(key="cowner_KZ-26-111").set_value("Никитин С. (мастер)")
    app.selectbox(key="cexec_KZ-26-111").set_value("Никитин С. (мастер)")
    app.text_input(key="cnext_KZ-26-111").set_value("Заказать новую столешницу")
    app.date_input(key="cdue_KZ-26-111").set_value(d(3))
    click(app, "Оформить рекламацию")
    assert not app.error, errors(app)
    _, orders = saved(app)
    assert orders["KZ-26-111-R1"]["order_type"] == "complaint"
    assert orders["KZ-26-111"]["deviations"][-1]["trigger"] == "complaint"
    assert app.selectbox(key="selected_id").value == "KZ-26-111-R1"  # открыта карточка рекламации
    go(app, "Панель руководителя")
    assert metric(app, "Рекламаций") == "2"


def test_close_on_deadline_day_is_not_late(app):
    # Позднее закрытие без отклонения проверяется в tests/test_domain.py: в демо-наборе нет
    # заказа на стадии 7 с уже прошедшим первоначальным сроком.
    card(app, "KZ-26-116")
    click(app, "Закрыть заказ")  # закрытие в день срока — не позднее
    assert not app.error, errors(app)
    _, orders = saved(app)
    assert orders["KZ-26-116"]["closed_at"] == T.isoformat()


def test_snapshot_is_immutable(app):
    go(app, "Панель руководителя")
    click(app, "Зафиксировать неделю")
    data, _ = saved(app)
    assert len(data["snapshots"]) == 1
    snap = data["snapshots"][0]["metrics"]["overdue"]
    assert snap == {"numerator": 2, "denominator": 17}
    card(app, "KZ-26-102")
    app.date_input(key="planned_KZ-26-102").set_value(d(10))
    set_dev(app, "opsdev_KZ-26-102", "measure_error", 1, "перезамер")
    click(app, "Сохранить")
    data, _ = saved(app)
    assert data["snapshots"][0]["metrics"]["overdue"] == {"numerator": 2, "denominator": 17}


def test_journal_is_human_readable(app):
    go(app, "Журнал изменений")
    df = app.dataframe[0].value
    row = df[(df["Заказ"] == "KZ-26-102") & (df["Что"] == "Стадия")].iloc[0]
    assert row["Было"] == "4. Производство" and row["Стало"] == "3. Подготовка к производству"
    assert "Ошибка замера" in set(df["Стало"])
    assert all(isinstance(v, str) for v in df["Было"])


def test_reset(app):
    go(app, "Панель руководителя")
    click(app, "Зафиксировать неделю")
    app.sidebar.checkbox(key="confirm_reset").check().run()
    app.sidebar.button(key="reset_btn").click().run()
    data, _ = saved(app)
    assert len(data["orders"]) == 24 and data["snapshots"] == []


# ---------------------------------------------------------------- регрессия QA (D14–D20)

def test_d15_two_tabs_no_silent_revert(tmp_path, monkeypatch):
    monkeypatch.setenv("KONTUR_DATA", str(tmp_path / "state.json"))
    monkeypatch.setenv("KONTUR_TODAY", T.isoformat())
    a = AppTest.from_file(APP, default_timeout=60).run()
    b = AppTest.from_file(APP, default_timeout=60).run()
    a.data_path = b.data_path = tmp_path / "state.json"
    card(a, "KZ-26-117")
    card(b, "KZ-26-117")
    a.selectbox(key="manager_KZ-26-117").set_value("Седов К.")
    click(a, "Сохранить")
    b.text_input(key="next_KZ-26-117").set_value("Отправить дилеру проект на подпись")
    click(b, "Сохранить")
    assert "изменён в другой вкладке" in errors(b)
    _, orders = saved(a)
    assert orders["KZ-26-117"]["manager"] == "Седов К."              # A не откатан
    assert orders["KZ-26-117"]["next_action"] == "Согласовать с дилером 3D-проект"
    assert b.selectbox(key="manager_KZ-26-117").value == "Седов К."   # поля B обновлены из файла
    b.text_input(key="next_KZ-26-117").set_value("Отправить дилеру проект на подпись")
    click(b, "Сохранить")
    assert not b.error, errors(b)
    _, orders = saved(a)
    assert orders["KZ-26-117"]["manager"] == "Седов К."
    assert orders["KZ-26-117"]["next_action"] == "Отправить дилеру проект на подпись"


def test_d15_own_consecutive_saves_no_false_conflict(app):
    card(app, "KZ-26-117")
    app.selectbox(key="manager_KZ-26-117").set_value("Седов К.")
    click(app, "Сохранить")
    app.text_input(key="next_KZ-26-117").set_value("Шаг 2")
    click(app, "Сохранить")
    assert not app.error, errors(app)
    _, orders = saved(app)
    assert orders["KZ-26-117"]["next_action"] == "Шаг 2"


def test_d14_form_does_not_assign_executor_silently(app):
    card(app, "KZ-26-106")
    app.selectbox(key="manager_KZ-26-106").set_value("Орлова Е.")
    click(app, "Сохранить")
    _, orders = saved(app)
    assert orders["KZ-26-106"]["manager"] == "Орлова Е." and orders["KZ-26-106"]["next_action_owner"] == ""


def test_d16_synthetic_label_in_main_area_on_every_page(app):
    for page in ["Требуют вмешательства", "Панель руководителя", "Реестр заказов", "Карточка заказа",
                 "Журнал изменений", "Правила"]:
        go(app, page)
        assert any("синтетических данных" in w.value for w in app.main.warning), page


def test_d17_closed_late_unconfirmed_section(app):
    subs = [s.value for s in app.subheader]
    assert "Закрыты с нарушением срока — причина не подтверждена — 1" in subs
    card(app, "KZ-26-122")
    click(app, "Подтвердить")
    go(app, "Требуют вмешательства")
    assert not any("причина не подтверждена" in s.value for s in app.subheader)


def test_d18_list_explains_difference_with_dashboard(app):
    assert any("главному" in c.value for c in app.caption)


def test_d19_one_snapshot_per_day(app):
    go(app, "Панель руководителя")
    click(app, "Зафиксировать неделю")
    click(app, "Зафиксировать неделю")
    data, _ = saved(app)
    assert len(data["snapshots"]) == 1 and "уже зафиксирован" in errors(app)


def test_d20_closed_late_shows_days(app):
    card(app, "KZ-26-112")
    assert any("Закрыт с нарушением первоначального срока на 16 дн." in m.value for m in app.markdown)
