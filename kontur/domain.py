"""Бизнес-логика «Контура заказов», версия 1.2.

Модуль не зависит от интерфейса. Правила BR-xx и требования FR-xx —
по docs/01_design.md v1.2. Дата расчёта (`today`) всегда передаётся явно,
поэтому правила детерминированы и проверяемы.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta
from typing import Any, Optional

# ---------------------------------------------------------------- справочники

STAGES: dict[int, str] = {
    1: "Замер",
    2: "Проектирование и согласование",
    3: "Подготовка к производству",
    4: "Производство",
    5: "Контроль качества и готовность к отгрузке",
    6: "Доставка и монтаж",
    7: "Приёмка и закрытие",
}
LAST_STAGE = max(STAGES)

CHANNELS: dict[str, str] = {"showroom": "Собственный шоурум", "dealer": "Дилер"}
ORDER_TYPES: dict[str, str] = {"main": "Основной", "complaint": "Рекламация"}

# Предварительный справочник для проверки гипотез, а не утверждённая классификация.
REASONS: dict[str, str] = {
    "measure_error": "Ошибка замера",
    "design_reapproval": "Повторное согласование проекта",
    "client_change": "Изменение клиентом требований",
    "material_shortage": "Нехватка материалов",
    "production_overload": "Перегрузка производства",
    "kitting_error": "Ошибка комплектации",
    "install_reschedule": "Перенос монтажа",
    "product_defect": "Дефект изделия",
    "logistics": "Проблема логистики",
    # v1.1: причины со стороны продаж, денег и клиента
    "unrealistic_deadline": "Нереалистичный срок при продаже",
    "awaiting_payment": "Ожидание оплаты клиентом",
    "design_error": "Ошибка проектирования / деталировки",
    "site_not_ready": "Неготовность объекта / клиент не принимает работу",
    "other": "Прочее",
}

TRIGGERS: dict[str, str] = {
    "block": "Блокировка", "deadline_move": "Перенос срока", "stage_back": "Возврат стадии",
    "late_close": "Позднее закрытие", "complaint": "Рекламация", "manual": "Вручную",
}

ST_OVERDUE, ST_BLOCKED, ST_RISK, ST_OK, ST_DONE = "overdue", "blocked", "at_risk", "ok", "done"
STATES: dict[str, str] = {
    ST_OVERDUE: "Просрочен", ST_BLOCKED: "Заблокирован", ST_RISK: "Под риском",
    ST_OK: "В норме", ST_DONE: "Завершён",
}
STATE_PRIORITY = [ST_OVERDUE, ST_BLOCKED, ST_RISK, ST_OK]

# kind: ops — влияет на состояние; fin — включает в список вмешательства (C-11);
# info — только показывается.
FLAGS: dict[str, tuple[str, str]] = {
    "deadline_overdue": ("ops", "Нарушен срок заказа"),
    "blocked": ("ops", "Заблокирован"),
    "deadline_soon": ("ops", "Приближается срок"),
    "no_manager": ("ops", "Нет менеджера заказа"),
    "no_stage_owner": ("ops", "Нет ответственного за стадию"),
    "no_next_owner": ("ops", "Нет исполнителя следующего действия"),
    "no_next_action": ("ops", "Нет следующего действия или срока"),
    "next_action_overdue": ("ops", "Просрочено следующее действие"),
    "action_after_deadline": ("ops", "Действие запланировано после срока заказа"),
    "stale": ("ops", "Статус давно не обновлялся"),
    "low_margin": ("fin", "Плановая маржинальность ниже порога канала"),
    "deadline_moved": ("info", "Срок перенесён"),
    "precontract": ("info", "До договора"),
    "baseline_unverified": ("info", "Первоначальный срок не сверен с договором"),
    "closed_late": ("info", "Закрыт с нарушением первоначального срока"),
}
OVERDUE_FLAGS = {"deadline_overdue"}
RISK_FLAGS = {"deadline_soon", "no_manager", "no_stage_owner", "no_next_owner", "no_next_action",
              "next_action_overdue", "action_after_deadline", "stale"}
OWNERSHIP_FLAGS = {"no_manager", "no_stage_owner", "no_next_owner", "no_next_action"}


@dataclass
class Settings:
    """Пороговые значения. Меняются администратором в конфигурации, не в интерфейсе (§8.3)."""
    warning_days: int = 3                 # BR-03, дней включительно
    stale_days: int = 7                   # BR-05
    margin_threshold_showroom: float = 25.0   # BR-14, демо-допущение
    margin_threshold_dealer: float = 15.0     # BR-14, утверждено руководителем проекта
    period_days: int = 28                 # BR-26

    def margin_threshold(self, channel: str) -> float:
        return self.margin_threshold_dealer if channel == "dealer" else self.margin_threshold_showroom

    def period_start(self, today: date) -> date:
        return today - timedelta(days=self.period_days - 1)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


# ---------------------------------------------------------------- модель

def _d(v) -> Optional[date]:
    return date.fromisoformat(v) if isinstance(v, str) and v else (v or None)


def _iso(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, date) else v


@dataclass
class Deviation:
    """Отклонение (BR-18, BR-19). У заказа их может быть несколько."""
    id: str
    reason: str
    origin_stage: int
    detected_stage: int
    detected_at: date
    comment: str
    trigger: str
    confirmed: bool = False
    confirmed_at: Optional[date] = None

    def to_dict(self) -> dict:
        return {**self.__dict__, "detected_at": _iso(self.detected_at),
                "confirmed_at": _iso(self.confirmed_at)}

    @classmethod
    def from_dict(cls, d: dict) -> "Deviation":
        return cls(**{**d, "detected_at": _d(d["detected_at"]), "confirmed_at": _d(d.get("confirmed_at"))})


@dataclass
class StageVisit:
    stage: int
    entered: date
    left: Optional[date] = None

    def days(self, today: date) -> int:
        return ((self.left or today) - self.entered).days


ORDER_DATE_FIELDS = ("created_at", "contract_date", "baseline_completion", "planned_completion",
                     "next_action_due", "status_updated_at", "closed_at")
MONEY_FIELDS = ("contract_price", "planned_cost")


@dataclass
class Order:
    id: str
    client: str
    channel: str
    sales_point: str
    stage: int
    created_at: date
    status_updated_at: date
    order_type: str = "main"
    parent_order_id: str = ""
    contract_date: Optional[date] = None
    baseline_completion: Optional[date] = None
    baseline_verified: bool = False
    planned_completion: Optional[date] = None
    manager: str = ""
    stage_owner: str = ""
    next_action: str = ""
    next_action_owner: str = ""
    next_action_due: Optional[date] = None
    is_blocked: bool = False
    block_deviation_id: str = ""
    contract_price: Optional[float] = None
    planned_cost: Optional[float] = None
    closed_at: Optional[date] = None
    deviations: list[Deviation] = field(default_factory=list)
    stage_history: list[StageVisit] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    @property
    def has_contract(self) -> bool:
        return self.contract_date is not None

    @property
    def stage_entered_at(self) -> Optional[date]:
        return self.stage_history[-1].entered if self.stage_history else None

    def deviation(self, dev_id: str) -> Optional[Deviation]:
        return next((d for d in self.deviations if d.id == dev_id), None)

    def to_dict(self) -> dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        for k in ORDER_DATE_FIELDS:
            d[k] = _iso(d[k])
        d["deviations"] = [x.to_dict() for x in self.deviations]
        d["stage_history"] = [{"stage": v.stage, "entered": _iso(v.entered), "left": _iso(v.left)}
                              for v in self.stage_history]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Order":
        d = dict(d)
        for k in ORDER_DATE_FIELDS:
            d[k] = _d(d.get(k))
        for k in MONEY_FIELDS:
            v = d.get(k)
            d[k] = None if v is None or v == "" else float(v)
        d["deviations"] = [Deviation.from_dict(x) for x in d.get("deviations", [])]
        d["stage_history"] = [StageVisit(v["stage"], _d(v["entered"]), _d(v.get("left")))
                              for v in d.get("stage_history", [])]
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def latest_deviation(o: Order) -> Optional[Deviation]:
    return max(o.deviations, key=lambda d: (d.detected_at, d.id), default=None)


def stage_durations(o: Order, today: date) -> dict[int, int]:
    """BR-20: длительность стадии = сумма всех её посещений, в днях."""
    out: dict[int, int] = {}
    for v in o.stage_history:
        out[v.stage] = out.get(v.stage, 0) + v.days(today)
    return out


# ---------------------------------------------------------------- плановая экономика (C-11)

@dataclass
class Finance:
    plan_md: Optional[float]     # плановый маржинальный доход
    plan_pct: Optional[float]    # плановая маржинальность, %
    note: str


def margin(revenue: Optional[float], cost: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """BR-11/BR-12: (маржинальный доход, маржинальность %). None — не определено."""
    if revenue is None or cost is None:
        return None, None
    md = revenue - cost
    return md, (None if revenue == 0 else md / revenue * 100)


def finance(o: Order) -> Finance:
    md, pct = margin(o.contract_price, o.planned_cost)
    if md is None:
        note = "Нет договорной выручки или плановой себестоимости"
    elif pct is None:
        note = "Выручка равна 0 — маржинальность не определена"
    else:
        note = ""
    return Finance(md, pct, note)


# ---------------------------------------------------------------- правила состояния

@dataclass
class Evaluation:
    states: list[str]
    primary: str
    flags: list[str]
    days_overdue: int
    deadline_shift_days: int
    finance: Finance

    @property
    def needs_attention(self) -> bool:
        return any(FLAGS[f][0] in ("ops", "fin") for f in self.flags)


def evaluate(o: Order, today: date, s: Settings) -> Evaluation:
    fin = finance(o)
    flags: list[str] = []
    shift = ((o.planned_completion - o.baseline_completion).days
             if o.planned_completion and o.baseline_completion else 0)

    if o.is_closed:
        late = o.baseline_completion is not None and o.closed_at > o.baseline_completion
        if late:
            flags.append("closed_late")
        if not o.baseline_verified:
            flags.append("baseline_unverified")
        days = (o.closed_at - o.baseline_completion).days if late else 0
        return Evaluation([ST_DONE], ST_DONE, flags, days, shift, fin)

    days_overdue = 0
    if o.has_contract and o.planned_completion:
        # BR-02: строго меньше сегодняшней даты; BR-03: 0..N дней включительно.
        left = (o.planned_completion - today).days
        if left < 0:
            flags.append("deadline_overdue")
            days_overdue = -left
        elif left <= s.warning_days:
            flags.append("deadline_soon")
    else:
        flags.append("precontract")  # BR-24: до договора срок заказа не оценивается
    if o.is_blocked:
        flags.append("blocked")
    if not o.manager.strip():
        flags.append("no_manager")
    if not o.stage_owner.strip():
        flags.append("no_stage_owner")
    if not o.next_action_owner.strip():
        flags.append("no_next_owner")
    if not o.next_action.strip() or o.next_action_due is None:
        flags.append("no_next_action")
    else:
        if o.next_action_due < today:
            flags.append("next_action_overdue")
        if ("deadline_overdue" not in flags and o.has_contract and o.planned_completion
                and o.next_action_due > o.planned_completion):
            flags.append("action_after_deadline")  # BR-25: ранний сигнал, пока срок не нарушен
    if (today - o.status_updated_at).days > s.stale_days:
        flags.append("stale")
    if shift > 0:
        flags.append("deadline_moved")
    if o.has_contract and not o.baseline_verified:
        flags.append("baseline_unverified")
    if o.order_type == "main" and (
            (fin.plan_pct is not None and fin.plan_pct < s.margin_threshold(o.channel))
            or (o.contract_price == 0 and (o.planned_cost or 0) > 0)):  # QA D13: выручка 0 — худший случай
        flags.append("low_margin")

    fs = set(flags)
    states = [st for st, hit in ((ST_OVERDUE, fs & OVERDUE_FLAGS), (ST_BLOCKED, "blocked" in fs),
                                 (ST_RISK, fs & RISK_FLAGS)) if hit] or [ST_OK]
    primary = next(st for st in STATE_PRIORITY if st in states)
    return Evaluation(states, primary, flags, days_overdue, shift, fin)


def _in(d: Optional[date], start: date, end: date) -> bool:
    return d is not None and start <= d <= end


_RANK = {ST_OVERDUE: 0, ST_BLOCKED: 1, ST_RISK: 2, ST_OK: 3, ST_DONE: 4}


def attention_list(orders: list[Order], today: date, s: Settings) -> list[tuple[Order, Evaluation]]:
    """FR-14: группы по главному состоянию; внутри — просроченные по дням просрочки,
    остальные по ближайшему сроку заказа (заказы без срока — в конце группы)."""
    items = [(o, evaluate(o, today, s)) for o in orders if not o.is_closed]
    items = [(o, e) for o, e in items if e.needs_attention]
    return sorted(items, key=lambda x: (_RANK[x[1].primary], -x[1].days_overdue,
                                        x[0].planned_completion or date.max, x[0].id))


def closed_late_unconfirmed(orders: list[Order], today: date, s: Settings) -> list[Order]:
    """QA D17: закрытые за период с нарушением срока, у которых последнее отклонение не подтверждено
    (или отклонения нет). Это повестка совещания наряду со списком вмешательства (B5)."""
    start = s.period_start(today)
    out = []
    for o in orders:
        if o.is_closed and _in(o.closed_at, start, today) and "closed_late" in evaluate(o, today, s).flags:
            last = latest_deviation(o)
            if last is None or not last.confirmed:
                out.append(o)
    return sorted(out, key=lambda o: o.closed_at, reverse=True)


def filter_orders(orders: list[Order], *, people=None, channels=None) -> list[Order]:
    """FR-10. Ответственный ищется среди менеджера, ответственного за стадию и исполнителя."""
    out = []
    for o in orders:
        if people and not {o.manager, o.stage_owner, o.next_action_owner} & set(people):
            continue
        if channels and o.channel not in channels:
            continue
        out.append(o)
    return out


# ---------------------------------------------------------------- показатели

@dataclass
class Metric:
    numerator: Optional[float]
    denominator: Optional[int]
    rule: str

    @property
    def pct(self) -> Optional[float]:
        if not self.denominator or self.numerator is None:
            return None
        return self.numerator / self.denominator * 100


def compute_kpi(orders: list[Order], today: date, s: Settings) -> dict[str, Any]:
    start = s.period_start(today)
    period = f"{start.strftime('%d.%m')}–{today.strftime('%d.%m.%Y')}"
    evs = [(o, evaluate(o, today, s)) for o in orders]
    active = [(o, e) for o, e in evs if not o.is_closed]
    contracted = [(o, e) for o, e in active if o.has_contract]
    n, nc = len(active), len(contracted)

    def cnt(rows, pred) -> int:
        return sum(1 for o, e in rows if pred(o, e))

    k: dict[str, Any] = {"period": period, "period_start": start}
    k["active"] = Metric(n, None, "Заказы без даты закрытия, включая заказы до договора")
    k["contracted"] = Metric(nc, n, "Активные с подписанным договором / все активные")
    k["overdue"] = Metric(cnt(contracted, lambda o, e: ST_OVERDUE in e.states), nc,
                          "Активные с договором, у которых плановый срок < сегодня / активные с договором")
    k["at_risk"] = Metric(cnt(active, lambda o, e: ST_RISK in e.states), n,
                          "Активные с хотя бы одним признаком риска (BR-05) / все активные")
    k["blocked"] = Metric(cnt(active, lambda o, e: ST_BLOCKED in e.states), n,
                          "Активные с блокировкой / все активные")
    k["ownership_gap"] = Metric(cnt(active, lambda o, e: bool(OWNERSHIP_FLAGS & set(e.flags))), n,
                                "Активные без менеджера, ответственного за стадию, исполнителя "
                                "или следующего действия со сроком / все активные")
    k["ownership_breakdown"] = {f: cnt(active, lambda o, e, f=f: f in e.flags) for f in
                                ("no_manager", "no_stage_owner", "no_next_owner", "no_next_action")}
    k["fresh"] = Metric(cnt(active, lambda o, e: "stale" not in e.flags), n,
                        f"Активные, чей статус обновлялся за последние {s.stale_days} дн. / все активные")
    k["by_stage"] = {st: cnt(active, lambda o, e, st=st: o.stage == st) for st in STAGES}

    # FR-18, BR-22/23/26: закрытые за период, от подтверждённого первоначального срока.
    def closed_late(rows) -> tuple[Metric, int]:
        verified = [(o, e) for o, e in rows if o.baseline_verified]
        excluded = len(rows) - len(verified)
        return Metric(cnt(verified, lambda o, e: "closed_late" in e.flags), len(verified),
                      "Закрытые позже подтверждённого первоначального срока / закрытые "
                      "с подтверждённым сроком"), excluded

    closed_all = [(o, e) for o, e in evs if o.is_closed]
    closed_period = [(o, e) for o, e in closed_all if _in(o.closed_at, start, today)]
    k["closed_late"], k["closed_late_excluded"] = closed_late(closed_period)
    k["closed_late_all"], k["closed_late_all_excluded"] = closed_late(closed_all)

    # FR-06, BR-19: отклонения за период по всем заказам, включая закрытые.
    devs = [d for o in orders for d in o.deviations if _in(d.detected_at, start, today)]
    k["deviations_total"] = len(devs)
    k["deviations_confirmed"] = sum(1 for d in devs if d.confirmed)
    k["dev_by_origin"] = {st: (sum(1 for d in devs if d.origin_stage == st),
                               sum(1 for d in devs if d.origin_stage == st and d.confirmed))
                          for st in STAGES}
    k["dev_by_reason"] = {r: (sum(1 for d in devs if d.reason == r),
                              sum(1 for d in devs if d.reason == r and d.confirmed)) for r in REASONS}

    # B5: заказы, требующие объяснения (просрочены, заблокированы, закрыты поздно за период),
    # у которых ПОСЛЕДНЕЕ отклонение подтверждено (старое подтверждённое не объясняет новый срыв).
    need = ([o for o, e in active if {ST_OVERDUE, ST_BLOCKED} & set(e.states)]
            + [o for o, e in closed_period if "closed_late" in e.flags])
    k["explained"] = Metric(sum(1 for o in need if latest_deviation(o) and latest_deviation(o).confirmed),
                            len(need), "Просроченные, заблокированные и закрытые поздно за период, у которых "
                            "последнее отклонение подтверждено на совещании / все такие заказы")
    k["baseline_verified"] = Metric(cnt(contracted, lambda o, e: o.baseline_verified), nc,
                                    "Активные с договором и сверенным первоначальным сроком / "
                                    "активные с договором")

    # FR-20: рекламации, созданные за период.
    k["complaints"] = Metric(sum(1 for o in orders if o.order_type == "complaint"
                                 and _in(o.created_at, start, today)), None,
                             "Заказы-рекламации, созданные за период")

    # C-11, BR-14/15: плановая маржинальность договоров за период, без рекламаций, по каналам.
    k["margin_by_channel"] = {}
    for ch in CHANNELS:
        rows = [(o, e) for o, e in evs if o.order_type == "main" and o.channel == ch
                and _in(o.contract_date, start, today)]
        full = [(o, e) for o, e in rows if e.finance.plan_md is not None]  # QA D13: и с выручкой 0
        rev = sum(o.contract_price for o, _ in full)
        md = sum(e.finance.plan_md for _, e in full)
        k["margin_by_channel"][ch] = {
            "pct": md / rev * 100 if rev else None, "with_data": len(full), "contracts": len(rows),
            "below": sum(1 for _, e in full if "low_margin" in e.flags),
            "threshold": s.margin_threshold(ch), "md": md}
    k["low_margin_active"] = cnt(active, lambda o, e: "low_margin" in e.flags)
    return k


SNAPSHOT_KEYS = {
    "active": "Активных заказов", "overdue": "Просрочено", "at_risk": "Под риском",
    "blocked": "Заблокировано", "ownership_gap": "Без владельца / исполнителя / шага",
    "fresh": "Статус обновлён за 7 дн.", "explained": "Срывы с подтверждённой причиной",
    "baseline_verified": "Первоначальный срок сверен", "closed_late": "Закрыто с нарушением срока (период)",
    "complaints": "Рекламаций за период",
}


def make_snapshot(k: dict[str, Any], today: date, user: str) -> dict:
    """FR-21, BR-28: неизменяемая копия показателей с числителями и знаменателями."""
    return {"date": today.isoformat(), "user": user, "period": k["period"],
            "metrics": {key: {"numerator": k[key].numerator, "denominator": k[key].denominator}
                        for key in SNAPSHOT_KEYS}}


# ---------------------------------------------------------------- изменения

FIELD_LABELS = {
    "stage": "Стадия", "manager": "Менеджер заказа", "stage_owner": "Ответственный за стадию",
    "next_action": "Следующее действие", "next_action_owner": "Исполнитель действия",
    "next_action_due": "Срок следующего действия", "planned_completion": "Плановый срок завершения",
    "is_blocked": "Блокировка", "contract_date": "Дата договора",
    "baseline_completion": "Первоначальный срок", "baseline_verified": "Первоначальный срок сверен",
    "contract_price": "Договорная выручка", "planned_cost": "Плановая себестоимость",
    "closed_at": "Дата закрытия", "deviation": "Отклонение", "deviation_confirmed": "Отклонение подтверждено",
    "complaint": "Рекламация",
}
EDITABLE = {"stage", "manager", "stage_owner", "next_action", "next_action_owner", "next_action_due",
            "planned_completion", "is_blocked", "contract_date", "baseline_completion",
            "baseline_verified", "contract_price", "planned_cost", "closed_at"}
# BR-05: изменение остальных полей (или новое отклонение) обновляет статус заказа.
NON_STATUS_FIELDS = {"contract_price", "planned_cost"}


@dataclass
class ChangeResult:
    order: Optional[Order]
    audit: list[dict]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _fmt(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def _entry(oid: str, user: str, fld: str, old, new, comment: str, ts: str) -> dict:
    return {"ts": ts, "order_id": oid, "user": user or "не указан", "field": fld,
            "field_label": FIELD_LABELS.get(fld, fld), "old": _fmt(old), "new": _fmt(new),
            "comment": comment}


def _validate_deviation(dev: dict, detected_stage: int) -> list[str]:
    e = []
    if dev.get("reason") not in REASONS:
        e.append("Отклонение: выберите причину из справочника")
    st = dev.get("origin_stage")
    if st not in STAGES:
        e.append("Отклонение: укажите стадию возникновения")
    elif st > detected_stage:
        e.append(f"Отклонение: стадия возникновения не может быть позже стадии обнаружения "
                 f"(«{STAGES[detected_stage]}»)")
    if not str(dev.get("comment", "")).strip():
        e.append("Отклонение: опишите, что произошло")
    return e


def _new_deviation(o: Order, dev: dict, trigger: str, today: date) -> Deviation:
    return Deviation(id=f"{o.id}-D{len(o.deviations) + 1}", reason=dev["reason"],
                     origin_stage=int(dev["origin_stage"]), detected_stage=o.stage, detected_at=today,
                     comment=str(dev["comment"]).strip(), trigger=trigger)


def apply_changes(o: Order, changes: dict[str, Any], *, today: date, user: str,
                  deviation: Optional[dict] = None, comment: str = "",
                  now: Optional[datetime] = None) -> ChangeResult:
    """Применяет изменения с проверкой правил BR-04, 09, 10, 21–25.

    `deviation` — {reason, origin_stage, comment}. Обязательно при возврате стадии,
    переносе срока, блокировке и позднем закрытии; без других изменений добавляет
    отклонение вручную. Исходный заказ не меняется."""
    if o.is_closed:
        return ChangeResult(None, [], ["Заказ завершён и не редактируется"])
    unknown = set(changes) - EDITABLE
    if unknown:
        return ChangeResult(None, [], [f"Поле нельзя изменить: {', '.join(sorted(unknown))}"])
    ch = {k: (v.strip() if isinstance(v, str) else v) for k, v in changes.items()}
    diff = {k: v for k, v in ch.items() if getattr(o, k) != v}
    dev = deviation if deviation and deviation.get("reason") else None
    if not diff and not dev:
        return ChangeResult(o, [], [])
    new = replace(o, **diff, deviations=list(o.deviations), stage_history=list(o.stage_history))
    # BR-21 (уточнено QA D14): исполнитель по умолчанию — ответственный за стадию, но только когда
    # следующее действие задаётся в этом же сохранении; правка других полей исполнителя не назначает.
    if ({"next_action", "next_action_due"} & set(diff) and new.next_action and not new.next_action_owner
            and new.stage_owner):
        new.next_action_owner = new.stage_owner
        diff["next_action_owner"] = new.stage_owner
    errors: list[str] = []
    trigger = None  # событие, которое требует отклонения

    for k in MONEY_FIELDS:
        v = getattr(new, k)
        if v is not None and (not isinstance(v, (int, float)) or v < 0):
            errors.append(f"{FIELD_LABELS[k]}: сумма должна быть неотрицательным числом")

    # BR-10: пропуск вперёд разрешён и фиксируется; возврат — с отклонением.
    if "stage" in diff:
        if new.stage not in STAGES:
            errors.append("Неизвестная стадия")
        else:
            if new.stage < o.stage:
                trigger = "stage_back"
            if not new.stage_owner:
                errors.append("При смене стадии укажите ответственного за новую стадию")
            if "next_action" not in diff and "next_action_due" not in diff:
                errors.append("При смене стадии обновите следующее действие или его срок")
            if not new.next_action or not new.next_action_owner or new.next_action_due is None:
                errors.append("При смене стадии нужны следующее действие, его исполнитель и срок")

    # BR-24: договор фиксирует сроки.
    if "contract_date" in diff:
        if o.has_contract:
            errors.append("Дата договора уже установлена и не меняется")
        elif new.contract_date is None:
            errors.append("Укажите дату договора")
        else:
            if new.contract_date > today or new.contract_date < o.created_at:
                errors.append("Дата договора должна быть между датой регистрации и сегодняшним днём")
            if new.baseline_completion is None or new.planned_completion is None:
                errors.append("С договором обязательны первоначальный и плановый сроки")
            elif min(new.baseline_completion, new.planned_completion) < new.contract_date:
                errors.append("Срок по договору не может быть раньше даты договора")  # QA D12
    # BR-23: первоначальный срок меняется только при подписании договора или при сверке
    # ещё не подтверждённого срока; подтверждённый срок не меняется.
    if "baseline_completion" in diff and o.has_contract and (o.baseline_verified or not new.baseline_verified):
        errors.append("Первоначальный срок меняется только вместе с его сверкой по договору; "
                      "подтверждённый срок не меняется")
    if "baseline_verified" in diff and o.baseline_verified and not new.baseline_verified:
        errors.append("Подтверждение первоначального срока нельзя снять")
    if new.baseline_verified and not (new.has_contract and new.baseline_completion):
        errors.append("Сверить можно только срок по подписанному договору")
    elif ("baseline_completion" in diff and new.has_contract and new.baseline_completion
          and new.baseline_completion < new.contract_date):
        errors.append("Первоначальный срок не может быть раньше даты договора")  # QA D12

    # BR-09: перенос планового срока — с отклонением.
    if "planned_completion" in diff:
        if new.has_contract and new.planned_completion is None:
            errors.append("У заказа с договором плановый срок обязателен")
        if new.planned_completion and new.planned_completion < new.created_at:
            errors.append("Плановый срок не может быть раньше регистрации заказа")
        if o.has_contract and o.planned_completion is not None:
            trigger = trigger or "deadline_move"

    # BR-04, BR-21: блокировка — через отклонение, с исполнителем и сроком снятия.
    if "is_blocked" in diff:
        if new.is_blocked:
            trigger = trigger or "block"
            if not new.next_action or not new.next_action_owner or new.next_action_due is None:
                errors.append("Блокировка требует действия по снятию, его исполнителя и срока")
        else:
            new.block_deviation_id = ""

    if new.next_action and new.next_action_due is None:
        errors.append("У следующего действия должен быть срок")
    if new.next_action_due is not None and not new.next_action:
        errors.append("Укажите, что именно нужно сделать к сроку")

    # Закрытие; BR-22 — позже первоначального срока только с отклонением.
    if "closed_at" in diff and new.closed_at is not None:
        if new.stage != LAST_STAGE:
            errors.append(f"Закрыть можно только заказ на стадии «{STAGES[LAST_STAGE]}»")
        if not new.has_contract:
            errors.append("Нельзя закрыть заказ без договора")
        if new.closed_at > today:
            errors.append("Дата закрытия не может быть в будущем")
        lower = max([x for x in (new.contract_date, new.stage_entered_at) if x], default=None)
        if lower and new.closed_at < lower:  # QA D11
            errors.append(f"Дата закрытия не может быть раньше {lower.strftime('%d.%m.%Y')} "
                          "(дата договора или входа в стадию приёмки)")
        if new.is_blocked:
            errors.append("Нельзя закрыть заблокированный заказ")
        if new.baseline_completion and new.closed_at > new.baseline_completion:
            trigger = trigger or "late_close"

    need_text = {"stage_back": "Возврат на предыдущую стадию", "deadline_move": "Перенос планового срока",
                 "block": "Блокировка", "late_close": "Закрытие позже первоначального срока"}
    if trigger and not dev:
        errors.append(f"{need_text[trigger]} требует отклонения: причина, стадия возникновения, описание")
    if dev:
        errors += _validate_deviation(dev, o.stage)

    if errors:
        return ChangeResult(None, [], errors)

    ts = (now or datetime.now()).isoformat(timespec="seconds")
    audit = [_entry(o.id, user, k, getattr(o, k), getattr(new, k), comment, ts) for k in diff]
    if dev:
        d = _new_deviation(o, dev, trigger or "manual", today)
        new.deviations.append(d)
        if new.is_blocked and "is_blocked" in diff:  # QA D10: не только при trigger == "block"
            new.block_deviation_id = d.id
        audit.append(_entry(o.id, user, "deviation", None, d.reason,
                            f"{TRIGGERS[d.trigger]}: {d.comment}", ts))
    if "stage" in diff:  # BR-20
        if new.stage_history:
            new.stage_history[-1] = replace(new.stage_history[-1], left=today)
        new.stage_history.append(StageVisit(new.stage, today))
    if new.closed_at and new.stage_history and new.stage_history[-1].left is None:
        new.stage_history[-1] = replace(new.stage_history[-1], left=new.closed_at)
    if set(diff) - NON_STATUS_FIELDS or dev:  # BR-05
        new.status_updated_at = today
    return ChangeResult(new, audit, [])


def confirm_deviation(o: Order, dev_id: str, *, today: date, user: str,
                      now: Optional[datetime] = None) -> ChangeResult:
    """BR-19: подтверждение причины на совещании. Доступно и для закрытых заказов."""
    d = o.deviation(dev_id)
    if d is None:
        return ChangeResult(None, [], ["Отклонение не найдено"])
    if d.confirmed:
        return ChangeResult(o, [], [])
    new = replace(o, deviations=[replace(x, confirmed=True, confirmed_at=today) if x.id == dev_id else x
                                 for x in o.deviations])
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    return ChangeResult(new, [_entry(o.id, user, "deviation_confirmed", False, True,
                                     f"{dev_id}: {REASONS[d.reason]}", ts)], [])


def create_complaint(parent: Order, existing_ids: set[str], *, today: date, user: str,
                     deviation: dict, stage: int, stage_owner: str, planned_completion: Optional[date],
                     next_action: str, next_action_owner: str, next_action_due: Optional[date],
                     planned_cost: Optional[float] = None, now: Optional[datetime] = None
                     ) -> tuple[Optional[Order], Optional[Order], list[dict], list[str]]:
    """FR-20, BR-27: рекламация — заказ со ссылкой на исходный; отклонение пишется в исходный заказ.

    Возвращает (рекламация, обновлённый исходный заказ, журнал, ошибки)."""
    errors = []
    if parent.order_type != "main":
        errors.append("Рекламацию можно оформить только по основному заказу")
    detected = LAST_STAGE if parent.is_closed else parent.stage
    errors += _validate_deviation(deviation or {}, detected)
    if stage not in STAGES:
        errors.append("Укажите стадию, с которой начинается работа по рекламации")
    if not stage_owner or not next_action or not next_action_owner or next_action_due is None:
        errors.append("Укажите ответственного, следующее действие, исполнителя и срок")
    if planned_completion is None or planned_completion < today:
        errors.append("Срок устранения рекламации не может быть в прошлом")
    if planned_cost is not None and planned_cost < 0:
        errors.append("Плановая себестоимость не может быть отрицательной")
    if errors:
        return None, None, [], errors

    n = 1
    while f"{parent.id}-R{n}" in existing_ids:
        n += 1
    cid = f"{parent.id}-R{n}"
    d = _new_deviation(replace(parent, stage=detected), deviation, "complaint", today)
    d.comment = f"{d.comment} (рекламация {cid})"
    new_parent = replace(parent, deviations=list(parent.deviations) + [d])
    complaint = Order(
        id=cid, client=parent.client, channel=parent.channel, sales_point=parent.sales_point,
        stage=stage, created_at=today, status_updated_at=today, order_type="complaint",
        parent_order_id=parent.id, contract_date=today, baseline_completion=planned_completion,
        baseline_verified=True, planned_completion=planned_completion, manager=parent.manager,
        stage_owner=stage_owner, next_action=next_action, next_action_owner=next_action_owner,
        next_action_due=next_action_due, contract_price=0.0, planned_cost=planned_cost,
        stage_history=[StageVisit(stage, today)])
    ts = (now or datetime.now()).isoformat(timespec="seconds")
    audit = [_entry(parent.id, user, "deviation", None, d.reason, f"Рекламация: {d.comment}", ts),
             _entry(cid, user, "complaint", None, parent.id, "Создана рекламация", ts)]
    return complaint, new_parent, audit, []


def validate_order(o: Order) -> list[str]:
    """Непротиворечивость записи (проверка демо-данных; на этапе 2 — импорта)."""
    e = []
    if o.stage not in STAGES:
        e.append("стадия")
    if o.channel not in CHANNELS or o.order_type not in ORDER_TYPES:
        e.append("канал или тип")
    if o.order_type == "complaint" and not o.parent_order_id:
        e.append("рекламация без исходного заказа")
    if o.has_contract and (o.baseline_completion is None or o.planned_completion is None):
        e.append("договор без сроков")
    if o.has_contract and o.contract_date < o.created_at:
        e.append("договор раньше регистрации")
    if o.status_updated_at < o.created_at:
        e.append("обновление раньше регистрации")
    if o.is_closed and (o.stage != LAST_STAGE or o.is_blocked or not o.has_contract):
        e.append("закрыт не на последней стадии, заблокирован или без договора")
    if o.is_blocked and not o.deviation(o.block_deviation_id):
        e.append("блокировка без отклонения")
    for d in o.deviations:
        if d.reason not in REASONS or d.origin_stage > d.detected_stage:
            e.append(f"отклонение {d.id}")
    for k in MONEY_FIELDS:
        v = getattr(o, k)
        if v is not None and v < 0:
            e.append(f"отрицательная сумма {k}")
    hist = o.stage_history
    if not hist or hist[-1].stage != o.stage:
        e.append("история стадий не совпадает с текущей стадией")
    for a, b in zip(hist, hist[1:]):
        if a.left is None or a.left != b.entered:
            e.append("разрыв в истории стадий")
    if any(v.left is not None and v.left < v.entered for v in hist):  # QA D11: проверялись не все посещения
        e.append("посещение стадии заканчивается раньше, чем начинается")
    return e
