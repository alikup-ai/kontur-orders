"""Синтетический демонстрационный набор (24 заказа), версия 1.2.

Все имена, суммы и даты вымышлены. Даты задаются относительно даты сброса,
чтобы сценарии оставались актуальными в день показа. Набор составлен под
заданные сценарии, поэтому любые «закономерности» в нём — следствие того,
как он составлен, а не наблюдение.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .domain import TRIGGERS, Deviation, Order, StageVisit

SCENARIOS = {
    "KZ-26-101": "Нормально идущий заказ",
    "KZ-26-102": "Просрочен из-за ошибки замера; возврат стадии и два отклонения",
    "KZ-26-103": "Под риском: проект не согласован, действие просрочено",
    "KZ-26-104": "Заблокирован нехваткой материалов; исполнитель — снабжение, а не мастер",
    "KZ-26-105": "Дилерская заявка до договора без менеджера и ответственного",
    "KZ-26-106": "Без следующего действия и исполнителя",
    "KZ-26-107": "Давно не обновлялся; первоначальный срок не сверен с договором",
    "KZ-26-108": "Высокая плановая маржа, переделка фасадов (отклонение подтверждено)",
    "KZ-26-109": "Действие запланировано после срока заказа",
    "KZ-26-110": "Договор подписан до замера, всё в норме",
    "KZ-26-111": "Завершён в срок",
    "KZ-26-112": "Завершён с нарушением первоначального срока (срок переносили)",
    "KZ-26-114": "Несколько признаков одновременно; маржа 19,5 % выше дилерского порога 15 %",
    "KZ-26-115": "Срок перенесён, по новому сроку в норме",
    "KZ-26-116": "Срок завершения — сегодня",
    "KZ-26-119": "Проблема логистики, срок близко",
    "KZ-26-121": "Плановая маржа 11,9 % ниже дилерского порога 15 %",
    "KZ-26-122": "Закрыт поздно, первоначальный срок не сверен — исключён из метрики срывов",
    "KZ-26-123": "Проектирование до договора",
    "KZ-26-124": "Закрыт в срок более 28 дней назад; по нему открыта рекламация",
    "KZ-26-124-R1": "Рекламация: гарантийная замена фасадов, выручка 0",
}

# Вымышленные сотрудники для выбора в формах (не реальные люди).
STAFF = [
    "Орлова Е.", "Седов К.", "Ким А.", "Белова Н.", "Гусев П.",
    "Лапин Д. (замерщик)", "Фомина О. (дизайнер)", "Рябов И. (дизайнер)",
    "Зуев М. (технолог)", "Никитин С. (мастер)", "Котова Л. (ОТК)",
    "Мельник В. (бригадир монтажа)", "Дорохов А. (логист)", "Яковлева Т. (снабжение)",
    "Пахомов Р. (склад)", "Коммерческий директор", "Собственник",
]


def build(today: date) -> list[Order]:
    def d(n):
        return None if n is None else today + timedelta(days=n)

    def hist(*visits, closed=None):
        out = [StageVisit(st, d(n)) for st, n in visits]
        for a, b in zip(out, out[1:]):
            a.left = b.entered
        if closed is not None:
            out[-1].left = d(closed)
        return out

    def dev(oid, i, reason, origin, detected, n, trigger, comment, confirmed_n=None):
        return Deviation(f"{oid}-D{i}", reason, origin, detected, d(n), comment, trigger,
                         confirmed_n is not None, d(confirmed_n))

    def o(id, client, channel, point, stage, created, status, history, *, contract="created",
          baseline=None, planned=None, verified=True, **kw):
        contract_d = d(created) if contract == "created" else d(contract)
        return Order(id=id, client=client, channel=channel, sales_point=point, stage=stage,
                     created_at=d(created), status_updated_at=d(status), contract_date=contract_d,
                     baseline_completion=d(baseline), planned_completion=d(planned if planned is not None else baseline),
                     baseline_verified=verified and contract_d is not None, stage_history=history, **kw)

    C, N, U = "Шоурум «Центр»", "Шоурум «Север»", "Шоурум «Юг»"
    MASTER, TECH, MEAS = "Никитин С. (мастер)", "Зуев М. (технолог)", "Лапин Д. (замерщик)"
    INST = "Мельник В. (бригадир монтажа)"
    return [
        o("KZ-26-101", "Смирнова Т. (частный клиент)", "showroom", C, 4, -40, -1,
          hist((1, -40), (2, -33), (3, -20), (4, -9)), baseline=21,
          manager="Орлова Е.", stage_owner=MASTER, next_action="Запустить фасады в покраску",
          next_action_owner=MASTER, next_action_due=d(4), contract_price=640_000, planned_cost=400_000),
        o("KZ-26-102", "Дилер Казань-1", "dealer", "Казань", 3, -62, -2,
          hist((1, -62), (2, -55), (3, -35), (4, -22), (3, -12)), baseline=-4,
          manager="Гусев П.", stage_owner=TECH,
          next_action="Повторный замер ниши и корректировка деталировки", next_action_owner=MEAS,
          next_action_due=d(1), contract_price=520_000, planned_cost=330_000,
          deviations=[dev("KZ-26-102", 1, "design_reapproval", 2, 2, -45, "manual",
                          "Две дополнительные итерации по раскладке верхних шкафов", -42),
                      dev("KZ-26-102", 2, "measure_error", 1, 4, -12, "stage_back",
                          "Ниша под холодильник на 40 мм меньше замера; переделка деталировки")]),
        o("KZ-26-103", "Ковалёв Д. (частный клиент)", "showroom", N, 2, -20, -5,
          hist((1, -20), (2, -13)), baseline=30,
          manager="Седов К.", stage_owner="Фомина О. (дизайнер)",
          next_action="Получить подпись клиента под проектом", next_action_owner="Фомина О. (дизайнер)",
          next_action_due=d(-2), contract_price=780_000, planned_cost=470_000,
          deviations=[dev("KZ-26-103", 1, "design_reapproval", 2, 2, -5, "manual",
                          "Клиент не подписал проект: третья итерация по острову")]),
        o("KZ-26-104", "Дилер Самара-2", "dealer", "Самара", 4, -45, -1,
          hist((1, -45), (2, -38), (3, -25), (4, -10)), baseline=18,
          manager="Гусев П.", stage_owner=MASTER, is_blocked=True, block_deviation_id="KZ-26-104-D1",
          next_action="Согласовать с дилером замену декора или подтвердить дату поставки",
          next_action_owner="Яковлева Т. (снабжение)", next_action_due=d(2),
          contract_price=450_000, planned_cost=290_000,
          deviations=[dev("KZ-26-104", 1, "material_shortage", 3, 4, -1, "block",
                          "Нет столешницы из кварцагломерата нужного декора: поставщик сдвинул отгрузку")]),
        o("KZ-26-105", "Дилер Пермь-1", "dealer", "Пермь", 1, -5, -5, hist((1, -5)), contract=None,
          next_action="Назначить менеджера заказа и замерщика", next_action_owner="Коммерческий директор",
          next_action_due=d(0)),
        o("KZ-26-106", "Громова И. (частный клиент)", "showroom", C, 6, -58, -2,
          hist((1, -58), (2, -50), (3, -36), (4, -25), (5, -10), (6, -4)), baseline=6,
          manager="Белова Н.", stage_owner=INST, contract_price=920_000, planned_cost=560_000),
        o("KZ-26-107", "Дилер Уфа-1", "dealer", "Уфа", 3, -35, -16,
          hist((1, -35), (2, -28), (3, -18)), baseline=28, verified=False,
          manager="Гусев П.", stage_owner=TECH, next_action="Получить от дилера подтверждение предоплаты",
          next_action_owner="Гусев П.", next_action_due=d(-9), contract_price=380_000, planned_cost=245_000),
        o("KZ-26-108", "Лебедев А. (частный клиент)", "showroom", N, 6, -70, -1,
          hist((1, -70), (2, -63), (3, -48), (4, -35), (5, -18), (6, -12)), baseline=7,
          manager="Седов К.", stage_owner=INST, next_action="Смонтировать переделанные фасады",
          next_action_owner=INST, next_action_due=d(5), contract_price=1_450_000, planned_cost=820_000,
          deviations=[dev("KZ-26-108", 1, "product_defect", 4, 6, -8, "manual",
                          "Скол эмали на 6 фасадах: повторная покраска и доставка", -6)]),
        o("KZ-26-109", "Морозова В. (частный клиент)", "showroom", U, 7, -75, -1,
          hist((1, -75), (2, -68), (3, -52), (4, -40), (5, -22), (6, -12), (7, -3)), baseline=2,
          manager="Ким А.", stage_owner="Ким А.", next_action="Подписать акт приёмки",
          next_action_owner="Ким А.", next_action_due=d(5), contract_price=700_000, planned_cost=455_000),
        o("KZ-26-110", "Петров С. (частный клиент)", "showroom", C, 1, -3, 0, hist((1, -3)), baseline=60,
          manager="Орлова Е.", stage_owner=MEAS, next_action="Выезд на замер", next_action_owner=MEAS,
          next_action_due=d(2), contract_price=560_000, planned_cost=350_000),
        o("KZ-26-111", "Зайцева М. (частный клиент)", "showroom", U, 7, -80, -10,
          hist((1, -80), (2, -72), (3, -58), (4, -45), (5, -28), (6, -20), (7, -14), closed=-10),
          baseline=-8, closed_at=d(-10), manager="Ким А.", stage_owner="Ким А.",
          contract_price=690_000, planned_cost=450_000),
        o("KZ-26-112", "Дилер Тюмень-1", "dealer", "Тюмень", 7, -95, -14,
          hist((1, -95), (2, -88), (3, -70), (4, -58), (5, -45), (6, -35), (7, -20), closed=-14),
          baseline=-30, planned=-12, closed_at=d(-14), manager="Гусев П.", stage_owner="Гусев П.",
          contract_price=830_000, planned_cost=520_000,
          deviations=[dev("KZ-26-112", 1, "site_not_ready", 6, 6, -30, "deadline_move",
                          "Объект клиента не готов к монтажу", -28),
                      dev("KZ-26-112", 2, "site_not_ready", 6, 7, -14, "late_close",
                          "Монтаж дважды переносился по просьбе клиента", -12)]),
        o("KZ-26-114", "Дилер Казань-2", "dealer", "Казань", 5, -60, -9,
          hist((1, -60), (2, -52), (3, -40), (4, -28), (5, -12)), baseline=-1,
          manager="Гусев П.", stage_owner="", is_blocked=True, block_deviation_id="KZ-26-114-D1",
          next_action="Доукомплектовать фурнитуру", next_action_owner="Пахомов Р. (склад)",
          next_action_due=d(-2), contract_price=410_000, planned_cost=330_000,
          deviations=[dev("KZ-26-114", 1, "kitting_error", 3, 5, -9, "block",
                          "Недокомплект фурнитуры для 3 модулей, отгрузка остановлена")]),
        o("KZ-26-115", "Новикова Е. (частный клиент)", "showroom", U, 4, -55, -3,
          hist((1, -55), (2, -48), (3, -35), (4, -20)), baseline=-10, planned=9,
          manager="Ким А.", stage_owner=MASTER, next_action="Подтвердить дату выхода из покраски",
          next_action_owner=MASTER, next_action_due=d(1), contract_price=870_000, planned_cost=540_000,
          deviations=[dev("KZ-26-115", 1, "production_overload", 4, 4, -10, "deadline_move",
                          "Загрузка покрасочного участка", -7)]),
        o("KZ-26-116", "Дилер Пермь-2", "dealer", "Пермь", 7, -66, -1,
          hist((1, -66), (2, -59), (3, -45), (4, -33), (5, -15), (6, -8), (7, -2)), baseline=0,
          manager="Белова Н.", stage_owner="Белова Н.", next_action="Подписать акт приёмки с дилером",
          next_action_owner="Белова Н.", next_action_due=d(0), contract_price=490_000, planned_cost=315_000),
        o("KZ-26-117", "Дилер Самара-1", "dealer", "Самара", 2, -14, -2, hist((1, -14), (2, -7)),
          baseline=45, manager="Гусев П.", stage_owner="Рябов И. (дизайнер)",
          next_action="Согласовать с дилером 3D-проект", next_action_owner="Рябов И. (дизайнер)",
          next_action_due=d(5), contract_price=610_000, planned_cost=385_000),
        o("KZ-26-118", "Орлов Г. (частный клиент)", "showroom", C, 5, -50, -1,
          hist((1, -50), (2, -43), (3, -30), (4, -18), (5, -3)), baseline=10,
          manager="Орлова Е.", stage_owner="Котова Л. (ОТК)",
          next_action="Проверка комплектности перед отгрузкой", next_action_owner="Котова Л. (ОТК)",
          next_action_due=d(2), contract_price=660_000, planned_cost=410_000),
        o("KZ-26-119", "Дилер Тюмень-2", "dealer", "Тюмень", 6, -64, -1,
          hist((1, -64), (2, -57), (3, -44), (4, -31), (5, -14), (6, -6)), baseline=3,
          manager="Гусев П.", stage_owner="Дорохов А. (логист)",
          next_action="Подтвердить у перевозчика дату отгрузки", next_action_owner="Дорохов А. (логист)",
          next_action_due=d(1), contract_price=540_000, planned_cost=350_000,
          deviations=[dev("KZ-26-119", 1, "logistics", 6, 6, -1, "manual",
                          "Отгрузка сборным грузом: перевозчик переносит машину")]),
        o("KZ-26-120", "Дилер Уфа-2", "dealer", "Уфа", 7, -70, -3,
          hist((1, -70), (2, -63), (3, -50), (4, -38), (5, -22), (6, -12), (7, -6), closed=-3),
          baseline=-1, closed_at=d(-3), manager="Гусев П.", stage_owner="Гусев П.",
          contract_price=560_000, planned_cost=360_000),
        o("KZ-26-121", "Дилер Пермь-3", "dealer", "Пермь", 3, -18, -2, hist((1, -18), (2, -12), (3, -4)),
          baseline=40, manager="Гусев П.", stage_owner=TECH, next_action="Передать деталировку в раскрой",
          next_action_owner=TECH, next_action_due=d(4), contract_price=395_000, planned_cost=348_000),
        o("KZ-26-122", "Соколова Ю. (частный клиент)", "showroom", N, 7, -100, -20,
          hist((1, -100), (2, -92), (3, -75), (4, -60), (5, -40), (6, -30), (7, -24), closed=-20),
          baseline=-27, planned=-22, verified=False, closed_at=d(-20), manager="Седов К.",
          stage_owner="Седов К.", contract_price=1_120_000, planned_cost=690_000,
          deviations=[dev("KZ-26-122", 1, "client_change", 4, 4, -40, "deadline_move",
                          "Клиент поменял фасады после запуска в производство", -38),
                      dev("KZ-26-122", 2, "client_change", 4, 7, -20, "late_close",
                          "Закрыт позже из-за замены фасадов")]),
        o("KZ-26-123", "Белкин Р. (частный клиент)", "showroom", U, 2, -10, -4, hist((1, -10), (2, -4)),
          contract=None, manager="Ким А.", stage_owner="Фомина О. (дизайнер)",
          next_action="Показать клиенту эскиз и согласовать бюджет", next_action_owner="Фомина О. (дизайнер)",
          next_action_due=d(3)),
        o("KZ-26-124", "Тихонова А. (частный клиент)", "showroom", N, 7, -110, -40,
          hist((1, -110), (2, -102), (3, -88), (4, -75), (5, -60), (6, -50), (7, -44), closed=-40),
          baseline=-38, closed_at=d(-40), manager="Седов К.", stage_owner="Седов К.",
          contract_price=720_000, planned_cost=460_000,
          deviations=[dev("KZ-26-124", 1, "product_defect", 4, 7, -12, "complaint",
                          "Отслоение плёнки на 3 фасадах (рекламация KZ-26-124-R1)")]),
        o("KZ-26-124-R1", "Тихонова А. (частный клиент)", "showroom", N, 4, -12, -1,
          hist((3, -12), (4, -6)), baseline=12, order_type="complaint", parent_order_id="KZ-26-124",
          manager="Седов К.", stage_owner=MASTER, next_action="Изготовить фасады повторно",
          next_action_owner=MASTER, next_action_due=d(6), contract_price=0, planned_cost=48_000),
    ]


def seed_audit(today: date) -> list[dict]:
    """Демо-история, согласованная с данными: переходы, переносы, блокировки и отклонения."""
    def ts(n: int) -> str:
        return datetime.combine(today + timedelta(days=n), datetime.min.time()).replace(
            hour=10).isoformat(timespec="seconds")

    def e(n, oid, fld, label, old, new, comment=""):
        return {"ts": ts(n), "order_id": oid, "user": "демо-история", "field": fld,
                "field_label": label, "old": old, "new": new, "comment": comment}

    def iso(n):
        return (today + timedelta(days=n)).isoformat()

    out = [
        e(-30, "KZ-26-112", "planned_completion", "Плановый срок завершения", iso(-30), iso(-12)),
        e(-12, "KZ-26-102", "stage", "Стадия", 4, 3),
        e(-10, "KZ-26-115", "planned_completion", "Плановый срок завершения", iso(-10), iso(9)),
        e(-1, "KZ-26-104", "is_blocked", "Блокировка", False, True),
        e(-12, "KZ-26-124-R1", "complaint", "Рекламация", None, "KZ-26-124", "Создана рекламация"),
    ]
    for o in build(today):
        for d in o.deviations:
            n = (d.detected_at - today).days
            out.append(e(n, o.id, "deviation", "Отклонение", None, d.reason,
                         f"{TRIGGERS[d.trigger]}: {d.comment}"))
            if d.confirmed:
                out.append(e((d.confirmed_at - today).days, o.id, "deviation_confirmed",
                             "Отклонение подтверждено", False, True, d.id))
    return sorted(out, key=lambda x: x["ts"])
