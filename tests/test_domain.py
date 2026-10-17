"""Тесты бизнес-правил v1.2 (BR-xx / FR-xx из docs/01_design.md)."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from kontur import domain as D

T = date(2026, 10, 17)
S = D.Settings()


def d(n):
    return T + timedelta(days=n)


def mk(**kw) -> D.Order:
    """Заказ «в норме» по умолчанию; тест меняет только то, что проверяет."""
    base = dict(id="T-1", client="Клиент", channel="showroom", sales_point="Ш", stage=4,
                created_at=d(-30), status_updated_at=d(-1), contract_date=d(-30),
                baseline_completion=d(20), baseline_verified=True, planned_completion=d(20),
                manager="М", stage_owner="О", next_action="Сделать", next_action_owner="И",
                next_action_due=d(5), contract_price=100_000, planned_cost=60_000,
                stage_history=[D.StageVisit(1, d(-30), d(-20)), D.StageVisit(4, d(-20))])
    base.update(kw)
    return D.Order(**base)


def ev(o, s=S):
    return D.evaluate(o, T, s)


DEV = {"reason": "measure_error", "origin_stage": 1, "comment": "ошибка"}


def change(o, deviation=None, **ch):
    return D.apply_changes(o, ch, today=T, user="Тест", deviation=deviation)


# ---------------------------------------------------------------- просрочка и граничные даты

class TestDeadlines:
    def test_normal_order_is_ok(self):
        e = ev(mk())
        assert e.states == [D.ST_OK] and e.flags == []

    def test_deadline_today_not_overdue_but_soon(self):
        e = ev(mk(planned_completion=T, baseline_completion=T, next_action_due=T))
        assert D.ST_OVERDUE not in e.states and "deadline_soon" in e.flags and e.primary == D.ST_RISK

    def test_deadline_passed_is_overdue(self):
        e = ev(mk(planned_completion=d(-3), baseline_completion=d(-3)))
        assert e.primary == D.ST_OVERDUE and e.days_overdue == 3

    @pytest.mark.parametrize("n,soon", [(0, True), (3, True), (4, False)])
    def test_warning_window_inclusive(self, n, soon):
        e = ev(mk(planned_completion=d(n), baseline_completion=d(n), next_action_due=d(0)))
        assert ("deadline_soon" in e.flags) is soon

    def test_precontract_never_overdue(self):
        e = ev(mk(contract_date=None, baseline_completion=None, planned_completion=d(-10),
                  baseline_verified=False))
        assert "precontract" in e.flags and D.ST_OVERDUE not in e.states and e.primary == D.ST_OK

    def test_action_after_deadline_only_before_breach(self):
        assert "action_after_deadline" in ev(mk(planned_completion=d(5), baseline_completion=d(5),
                                                next_action_due=d(6))).flags
        assert "action_after_deadline" not in ev(mk(planned_completion=d(5), baseline_completion=d(5),
                                                    next_action_due=d(5))).flags
        overdue = ev(mk(planned_completion=d(-1), baseline_completion=d(-1), next_action_due=d(2)))
        assert "action_after_deadline" not in overdue.flags  # для просроченного — шум

    def test_closed_late_vs_baseline_even_after_move(self):
        o = mk(stage=7, baseline_completion=d(-30), planned_completion=d(-10), closed_at=d(-12))
        e = ev(o)
        assert e.states == [D.ST_DONE] and "closed_late" in e.flags and e.days_overdue == 18

    def test_closed_on_time(self):
        assert ev(mk(stage=7, baseline_completion=d(-5), planned_completion=d(-5), closed_at=d(-5))).flags == []

    def test_moved_deadline_flag_is_info(self):
        e = ev(mk(baseline_completion=d(5), planned_completion=d(20)))
        assert "deadline_moved" in e.flags and e.deadline_shift_days == 15 and e.primary == D.ST_OK


# ---------------------------------------------------------------- ответственность и свежесть

class TestOwnership:
    def test_no_stage_owner(self):
        assert "no_stage_owner" in ev(mk(stage_owner="")).flags

    def test_whitespace_manager_missing(self):
        assert "no_manager" in ev(mk(manager="  ")).flags

    def test_no_executor_is_risk(self):
        e = ev(mk(next_action_owner=""))
        assert "no_next_owner" in e.flags and e.primary == D.ST_RISK

    def test_no_next_action_or_due(self):
        assert "no_next_action" in ev(mk(next_action="")).flags
        assert "no_next_action" in ev(mk(next_action_due=None)).flags

    def test_next_action_overdue(self):
        assert "next_action_overdue" in ev(mk(next_action_due=d(-1))).flags

    @pytest.mark.parametrize("n,stale", [(7, False), (8, True)])
    def test_stale_boundary(self, n, stale):
        assert ("stale" in ev(mk(status_updated_at=d(-n))).flags) is stale

    def test_blocked_but_not_overdue(self):
        e = ev(mk(is_blocked=True))
        assert e.states == [D.ST_BLOCKED]

    def test_blocked_and_overdue_in_production(self):
        e = ev(mk(stage=4, is_blocked=True, planned_completion=d(-2), baseline_completion=d(-2)))
        assert e.states[:2] == [D.ST_OVERDUE, D.ST_BLOCKED] and e.primary == D.ST_OVERDUE

    def test_multiple_flags_at_once(self):
        e = ev(mk(planned_completion=d(-1), baseline_completion=d(-1), stage_owner="",
                  status_updated_at=d(-20), next_action_due=d(-5), is_blocked=True))
        assert set(e.states) == {D.ST_OVERDUE, D.ST_BLOCKED, D.ST_RISK}
        assert {"deadline_overdue", "blocked", "no_stage_owner", "stale", "next_action_overdue"} <= set(e.flags)


# ---------------------------------------------------------------- плановая экономика (C-11)

class TestFinance:
    def test_plan_margin(self):
        f = D.finance(mk(contract_price=640_000, planned_cost=400_000))
        assert f.plan_md == 240_000 and f.plan_pct == pytest.approx(37.5)

    def test_zero_revenue(self):
        f = D.finance(mk(contract_price=0, planned_cost=48_000))
        assert f.plan_md == -48_000 and f.plan_pct is None and "Выручка равна 0" in f.note

    def test_missing_data(self):
        f = D.finance(mk(contract_price=None))
        assert f.plan_md is None and f.plan_pct is None and f.note

    def test_margin_function_edges(self):
        assert D.margin(None, 1) == (None, None)
        assert D.margin(0, 0) == (0, None)

    @pytest.mark.parametrize("channel,cost,low", [
        ("showroom", 75_000, False), ("showroom", 75_001, True),   # порог 25 %: ровно 25 % — не ниже
        ("dealer", 85_000, False), ("dealer", 85_001, True),       # порог 15 %
        ("dealer", 80_500, False)])                                # 19,5 % у дилера — норма
    def test_threshold_by_channel(self, channel, cost, low):
        o = mk(channel=channel, contract_price=100_000, planned_cost=cost)
        assert ("low_margin" in ev(o).flags) is low

    def test_complaint_not_flagged_low_margin(self):
        assert "low_margin" not in ev(mk(order_type="complaint", parent_order_id="X",
                                         contract_price=10, planned_cost=9)).flags

    def test_low_margin_alone_needs_attention_but_ok_state(self):
        e = ev(mk(contract_price=100_000, planned_cost=90_000))
        assert e.primary == D.ST_OK and e.needs_attention


# ---------------------------------------------------------------- переходы и отклонения

class TestChanges:
    STEP = dict(stage_owner="Новый", next_action="Шаг", next_action_owner="Новый", next_action_due=d(3))

    def test_forward_and_history(self):
        o = mk(stage=3, stage_history=[D.StageVisit(3, d(-10))])
        r = change(o, stage=4, **self.STEP)
        assert r.ok and r.order.stage == 4 and r.order.status_updated_at == T
        assert [(v.stage, v.entered, v.left) for v in r.order.stage_history] == [(3, d(-10), T), (4, T, None)]
        assert o.stage == 3 and len(o.stage_history) == 1  # исходный объект не изменён
        st = next(a for a in r.audit if a["field"] == "stage")
        assert (st["old"], st["new"], st["user"]) == (3, 4, "Тест")

    def test_skip_forward_allowed_and_recorded(self):
        r = change(mk(stage=2, stage_history=[D.StageVisit(2, d(-5))]), stage=5, **self.STEP)
        assert r.ok and [v.stage for v in r.order.stage_history] == [2, 5]

    def test_stage_change_requires_owner_executor_action(self):
        r = change(mk(stage=3, stage_owner=""), stage=4)
        joined = " ".join(r.errors)
        assert not r.ok and "ответственного" in joined and "следующее действие" in joined
        # BR-21 (после QA D14): действие задаётся в этом сохранении, исполнитель пуст —
        # подставляется ответственный за стадию, и это видно в журнале.
        r = change(mk(stage=3), stage=4, **{**self.STEP, "next_action_owner": ""})
        assert r.ok and r.order.next_action_owner == "Новый"
        assert any(a["field"] == "next_action_owner" for a in r.audit)

    def test_back_requires_deviation(self):
        assert not change(mk(stage=4), stage=2, **self.STEP).ok
        r = change(mk(stage=4), DEV, stage=2, **self.STEP)
        assert r.ok and r.order.deviations[-1].trigger == "stage_back"
        assert r.order.deviations[-1].detected_stage == 4 and r.order.deviations[-1].origin_stage == 1

    def test_stage_revisit_durations_sum(self):
        o = mk(stage=3, stage_history=[D.StageVisit(3, d(-20))])
        o = change(o, stage=4, **self.STEP).order                      # 3: 20 дн.
        o = D.apply_changes(o, {"stage": 3, **self.STEP, "next_action": "Назад"}, today=d(5), user="u",
                            deviation=DEV).order                       # 4: 5 дн.
        o = D.apply_changes(o, {"stage": 4, **self.STEP, "next_action": "Вперёд"}, today=d(8), user="u").order
        assert D.stage_durations(o, d(10)) == {3: 20 + 3, 4: 5 + 2}

    def test_deadline_move_requires_deviation(self):
        o = mk()
        assert not change(o, planned_completion=d(40)).ok
        r = change(o, {"reason": "client_change", "origin_stage": 2, "comment": "клиент"}, planned_completion=d(40))
        assert r.ok and r.order.baseline_completion == o.baseline_completion
        assert "deadline_moved" in ev(r.order).flags and r.order.deviations[-1].trigger == "deadline_move"

    def test_block_requires_deviation_and_executor(self):
        assert not change(mk(), is_blocked=True).ok
        r = change(mk(next_action_owner=""), {"reason": "material_shortage", "origin_stage": 3,
                                              "comment": "нет ЛДСП"}, is_blocked=True)
        assert not r.ok and "исполнителя" in " ".join(r.errors)
        r = change(mk(), {"reason": "material_shortage", "origin_stage": 3, "comment": "нет ЛДСП"}, is_blocked=True)
        assert r.ok and r.order.block_deviation_id == r.order.deviations[-1].id
        r2 = D.apply_changes(r.order, {"is_blocked": False}, today=T, user="u")
        assert r2.ok and r2.order.block_deviation_id == "" and len(r2.order.deviations) == 1

    def test_deviation_origin_cannot_be_after_detection(self):
        r = change(mk(stage=3), {"reason": "other", "origin_stage": 5, "comment": "x"})
        assert not r.ok and "позже стадии обнаружения" in r.errors[0]

    def test_deviation_validation(self):
        assert not change(mk(), {"reason": "nonsense", "origin_stage": 1, "comment": "x"}).ok
        assert not change(mk(), {"reason": "other", "origin_stage": 1, "comment": " "}).ok

    def test_second_deviation_does_not_overwrite_first(self):
        o = change(mk(), DEV).order
        o = D.apply_changes(o, {}, today=T, user="u", deviation={"reason": "logistics", "origin_stage": 4,
                                                                 "comment": "машина"}).order
        assert [x.reason for x in o.deviations] == ["measure_error", "logistics"]
        assert [x.id for x in o.deviations] == ["T-1-D1", "T-1-D2"]

    def test_finance_edit_does_not_refresh_status(self):
        o = mk(status_updated_at=d(-10))
        r = change(o, contract_price=110_000.0)
        assert r.ok and r.order.status_updated_at == d(-10) and "stale" in ev(r.order).flags
        r = change(o, next_action="Новый шаг")
        assert r.order.status_updated_at == T

    def test_contract_signing(self):
        o = mk(contract_date=None, baseline_completion=None, planned_completion=None, baseline_verified=False)
        assert not change(o, contract_date=T).ok
        assert not change(o, contract_date=d(1), baseline_completion=d(40), planned_completion=d(40)).ok
        assert not change(o, contract_date=d(-31), baseline_completion=d(40), planned_completion=d(40)).ok
        r = change(o, contract_date=T, baseline_completion=d(40), planned_completion=d(40), baseline_verified=True)
        assert r.ok and r.order.has_contract and r.order.baseline_verified
        assert not change(r.order, contract_date=d(-1)).ok  # дата договора не меняется

    def test_baseline_verification_rules(self):
        unverified = mk(baseline_verified=False)
        assert not change(unverified, baseline_completion=d(25)).ok           # без сверки — нельзя
        r = change(unverified, baseline_completion=d(25), baseline_verified=True)
        assert r.ok and r.order.baseline_completion == d(25)
        assert not change(r.order, baseline_completion=d(30), baseline_verified=True).ok  # сверенный не меняется
        assert not change(r.order, baseline_verified=False).ok

    def test_close_rules(self):
        assert not change(mk(stage=6), closed_at=T).ok
        assert not change(mk(stage=7), closed_at=d(1)).ok
        assert not change(mk(stage=7, contract_date=None, baseline_completion=None), closed_at=T).ok
        r = change(mk(stage=7), closed_at=T)
        assert r.ok and ev(r.order).primary == D.ST_DONE and r.order.stage_history[-1].left == T

    def test_late_close_requires_deviation(self):
        late = mk(stage=7, baseline_completion=d(-3), planned_completion=d(-3))
        r = change(late, closed_at=T)
        assert not r.ok and "Закрытие позже первоначального срока" in r.errors[0]
        r = change(late, {"reason": "site_not_ready", "origin_stage": 7, "comment": "акт не подписан"}, closed_at=T)
        assert r.ok and r.order.deviations[-1].trigger == "late_close" and "closed_late" in ev(r.order).flags

    def test_closed_order_read_only_but_deviation_confirmable(self):
        o = mk(stage=7, closed_at=d(-1), deviations=[D.Deviation("T-1-D1", "other", 7, 7, d(-1), "x", "late_close")])
        assert not change(o, manager="Другой").ok
        r = D.confirm_deviation(o, "T-1-D1", today=T, user="u")
        assert r.ok and r.order.deviations[0].confirmed and r.order.deviations[0].confirmed_at == T
        assert D.confirm_deviation(r.order, "T-1-D1", today=T, user="u").audit == []
        assert not D.confirm_deviation(o, "нет", today=T, user="u").ok

    def test_negative_money_and_unknown_field(self):
        assert not change(mk(), planned_cost=-1.0).ok
        assert not change(mk(), client="Другой").ok

    def test_no_changes_no_audit(self):
        r = change(mk(), manager="М")
        assert r.ok and r.audit == []


# ---------------------------------------------------------------- рекламации

class TestComplaints:
    def args(self, **kw):
        a = dict(today=T, user="u", deviation={"reason": "product_defect", "origin_stage": 4, "comment": "скол"},
                 stage=4, stage_owner="Мастер", planned_completion=d(10), next_action="Изготовить",
                 next_action_owner="Мастер", next_action_due=d(3))
        a.update(kw)
        return a

    def test_create(self):
        parent = mk(stage=7, closed_at=d(-5))
        comp, new_parent, audit, errs = D.create_complaint(parent, {"T-1"}, **self.args())
        assert not errs and comp.id == "T-1-R1" and comp.order_type == "complaint"
        assert comp.parent_order_id == "T-1" and comp.contract_price == 0 and D.validate_order(comp) == []
        dev = new_parent.deviations[-1]
        assert dev.trigger == "complaint" and dev.detected_stage == 7 and "T-1-R1" in dev.comment
        assert len(parent.deviations) == 0  # исходный не изменён
        assert {a["order_id"] for a in audit} == {"T-1", "T-1-R1"}

    def test_requires_deviation_and_fields(self):
        assert D.create_complaint(mk(), set(), **self.args(deviation={}))[3]
        assert D.create_complaint(mk(), set(), **self.args(stage_owner=""))[3]
        assert D.create_complaint(mk(), set(), **self.args(planned_completion=d(-1)))[3]
        assert D.create_complaint(mk(order_type="complaint", parent_order_id="X"), set(), **self.args())[3]

    def test_unique_id(self):
        comp = D.create_complaint(mk(), {"T-1", "T-1-R1"}, **self.args())[0]
        assert comp.id == "T-1-R2"


# ---------------------------------------------------------------- показатели

class TestKpi:
    def orders(self):
        dev_ok = D.Deviation("B-D1", "measure_error", 1, 4, d(-3), "x", "manual", True, d(-2))
        return [
            mk(id="A"),                                                                   # норма
            mk(id="B", planned_completion=d(-1), baseline_completion=d(-1), deviations=[dev_ok]),  # просрочен, объяснён
            mk(id="C", is_blocked=True, channel="dealer",
               deviations=[D.Deviation("C-D1", "material_shortage", 3, 4, d(-50), "x", "block")]),  # вне периода
            mk(id="D", stage_owner="", channel="dealer"),
            mk(id="P", contract_date=None, baseline_completion=None, planned_completion=None,
               baseline_verified=False),                                                  # до договора
            mk(id="E", stage=7, baseline_completion=d(-10), planned_completion=d(-10), closed_at=d(-5)),  # поздно
            mk(id="F", stage=7, baseline_completion=d(-10), planned_completion=d(-10), closed_at=d(-12)),  # в срок
            mk(id="G", stage=7, baseline_completion=d(-38), planned_completion=d(-38), closed_at=d(-40)),  # вне периода, в срок
            mk(id="H", stage=7, baseline_completion=d(-10), planned_completion=d(-10), closed_at=d(-5),
               baseline_verified=False),                                                  # исключён
        ]

    def test_shares_and_denominators(self):
        k = D.compute_kpi(self.orders(), T, S)
        assert k["active"].numerator == 5 and (k["contracted"].numerator, k["contracted"].denominator) == (4, 5)
        assert (k["overdue"].numerator, k["overdue"].denominator) == (1, 4)  # без заказа до договора
        assert k["overdue"].pct == pytest.approx(25.0)
        assert (k["blocked"].numerator, k["blocked"].denominator) == (1, 5)
        assert k["ownership_gap"].numerator == 1 and k["ownership_breakdown"]["no_stage_owner"] == 1
        assert (k["fresh"].numerator, k["fresh"].denominator) == (5, 5)
        assert (k["baseline_verified"].numerator, k["baseline_verified"].denominator) == (4, 4)

    def test_closed_late_period_and_exclusions(self):
        k = D.compute_kpi(self.orders(), T, S)
        assert (k["closed_late"].numerator, k["closed_late"].denominator) == (1, 2)   # E из {E, F}
        assert k["closed_late_excluded"] == 1                                          # H
        assert (k["closed_late_all"].numerator, k["closed_late_all"].denominator) == (1, 3)  # + G

    def test_deviations_in_period_include_closed(self):
        orders = self.orders()
        orders[5] = replace(orders[5], deviations=[D.Deviation("E-D1", "site_not_ready", 6, 7, d(-5), "x",
                                                               "late_close")])
        k = D.compute_kpi(orders, T, S)
        assert k["deviations_total"] == 2 and k["deviations_confirmed"] == 1          # C-D1 вне периода
        assert k["dev_by_reason"]["site_not_ready"] == (1, 0) and k["dev_by_origin"][1] == (1, 1)

    def test_explained_uses_latest_deviation(self):
        k = D.compute_kpi(self.orders(), T, S)
        # B из {B, C, E, H}: H закрыт поздно по несверенному сроку — из метрики срывов он исключён,
        # но объяснение причины требуется и для него.
        assert (k["explained"].numerator, k["explained"].denominator) == (1, 4)
        orders = self.orders()
        newer = D.Deviation("B-D2", "logistics", 4, 4, d(-1), "y", "manual")
        orders[1] = replace(orders[1], deviations=orders[1].deviations + [newer])
        assert D.compute_kpi(orders, T, S)["explained"].numerator == 0                # старое не объясняет

    def test_complaints_and_margin_by_channel(self):
        orders = [mk(id="S1", contract_date=d(-3), contract_price=100_000, planned_cost=60_000),
                  mk(id="S2", contract_date=d(-3), contract_price=300_000, planned_cost=240_000),
                  mk(id="DL", channel="dealer", contract_date=d(-3), contract_price=100_000, planned_cost=90_000),
                  mk(id="OLD", contract_date=d(-40), created_at=d(-40), contract_price=100, planned_cost=99),
                  mk(id="R", order_type="complaint", parent_order_id="S1", created_at=d(-2), contract_date=d(-2),
                     contract_price=0, planned_cost=5_000)]
        k = D.compute_kpi(orders, T, S)
        sh, dl = k["margin_by_channel"]["showroom"], k["margin_by_channel"]["dealer"]
        assert sh["pct"] == pytest.approx(25.0) and (sh["with_data"], sh["contracts"]) == (2, 2)  # взвешенно
        assert sh["below"] == 1 and dl["below"] == 1 and dl["threshold"] == 15.0
        assert k["complaints"].numerator == 1

    def test_empty_set(self):
        k = D.compute_kpi([], T, S)
        assert k["active"].numerator == 0 and k["overdue"].pct is None and k["closed_late"].pct is None

    def test_recalc_after_change(self):
        orders = self.orders()
        before = D.compute_kpi(orders, T, S)["overdue"].numerator
        b = next(o for o in orders if o.id == "B")
        r = change(b, {"reason": "client_change", "origin_stage": 2, "comment": "клиент"}, planned_completion=d(10))
        orders = [r.order if o.id == "B" else o for o in orders]
        assert D.compute_kpi(orders, T, S)["overdue"].numerator == before - 1

    def test_filters(self):
        orders = self.orders() + [mk(id="X", manager="Другой", stage_owner="Другой", next_action_owner="Снабжение")]
        assert {o.id for o in D.filter_orders(orders, channels=["dealer"])} == {"C", "D"}
        assert {o.id for o in D.filter_orders(orders, people=["Снабжение"])} == {"X"}
        assert len(D.filter_orders(orders)) == len(orders)

    def test_attention_order(self):
        orders = [mk(id="soon-late", planned_completion=d(2), baseline_completion=d(2), next_action_due=d(1)),
                  mk(id="soon-early", planned_completion=d(1), baseline_completion=d(1), next_action_due=d(1)),
                  mk(id="over-1", planned_completion=d(-1), baseline_completion=d(-1)),
                  mk(id="over-5", planned_completion=d(-5), baseline_completion=d(-5)),
                  mk(id="blocked", is_blocked=True),
                  mk(id="many-flags", stage_owner="", manager="", status_updated_at=d(-20), planned_completion=d(30),
                     baseline_completion=d(30)),
                  mk(id="low", contract_price=100, planned_cost=99), mk(id="ok")]
        ids = [o.id for o, _ in D.attention_list(orders, T, S)]
        assert ids == ["over-5", "over-1", "blocked", "soon-early", "soon-late", "many-flags", "low"]

    def test_snapshot_is_a_copy(self):
        orders = self.orders()
        snap = D.make_snapshot(D.compute_kpi(orders, T, S), T, "u")
        assert snap["metrics"]["overdue"] == {"numerator": 1, "denominator": 4}
        assert set(snap["metrics"]) == set(D.SNAPSHOT_KEYS)
        orders[1] = replace(orders[1], planned_completion=d(10))
        assert snap["metrics"]["overdue"] == {"numerator": 1, "denominator": 4}


# ---------------------------------------------------------------- регрессия QA (D10–D14, D17)

class TestQaRegression:
    BLOCK = {"reason": "material_shortage", "origin_stage": 3, "comment": "нет ЛДСП"}

    def test_d10_block_with_deadline_move_links_deviation(self):
        r = change(mk(), self.BLOCK, is_blocked=True, planned_completion=d(30))
        assert r.ok and r.order.block_deviation_id == r.order.deviations[-1].id
        assert D.validate_order(r.order) == []

    def test_d10_block_with_stage_back_links_deviation(self):
        r = change(mk(stage=4), self.BLOCK, is_blocked=True, stage=3, stage_owner="Т", next_action="Ш",
                   next_action_owner="Т", next_action_due=d(2))
        assert r.ok and r.order.block_deviation_id == r.order.deviations[-1].id

    def test_d11_close_date_not_before_contract_or_stage_entry(self):
        o = mk(stage=7, stage_history=[D.StageVisit(6, d(-30), d(-3)), D.StageVisit(7, d(-3))])
        assert not change(o, closed_at=d(-4)).ok
        assert not change(o, closed_at=d(-200)).ok
        assert change(o, closed_at=d(-3)).ok

    def test_d11_validator_checks_every_visit(self):
        o = mk(stage_history=[D.StageVisit(4, d(-1), d(-5))])
        assert any("раньше, чем начинается" in x for x in D.validate_order(o))

    def test_d12_contract_deadline_not_before_contract(self):
        o = mk(contract_date=None, baseline_completion=None, planned_completion=None, baseline_verified=False)
        assert not change(o, contract_date=T, baseline_completion=d(-5), planned_completion=d(-5),
                          baseline_verified=True).ok
        u = mk(baseline_verified=False)
        assert not change(u, baseline_completion=d(-31), baseline_verified=True).ok

    def test_d13_zero_revenue_main_order_flagged_and_counted(self):
        z = mk(id="Z", contract_price=0.0, planned_cost=350_000.0, contract_date=d(-3))
        assert "low_margin" in ev(z).flags
        n = mk(id="N", contract_price=100_000.0, planned_cost=60_000.0, contract_date=d(-3))
        m = D.compute_kpi([n, z], T, S)["margin_by_channel"]["showroom"]
        assert m["with_data"] == 2 and m["md"] == 40_000 - 350_000
        assert m["pct"] == pytest.approx(-310.0)  # Σ МД / Σ выручки, убыток не скрыт

    def test_d14_executor_not_assigned_by_unrelated_edit(self):
        o = mk(next_action="", next_action_due=None, next_action_owner="")
        r = change(o, manager="Новый менеджер")
        assert r.ok and r.order.next_action_owner == "" and "no_next_owner" in ev(r.order).flags

    def test_d14_executor_defaults_when_action_set(self):
        o = mk(next_action="", next_action_due=None, next_action_owner="", stage_owner="Мастер")
        r = change(o, next_action="Покрасить", next_action_due=d(3))
        assert r.ok and r.order.next_action_owner == "Мастер"
        assert any(a["field"] == "next_action_owner" for a in r.audit)

    def test_d17_closed_late_unconfirmed(self):
        late = mk(id="L", stage=7, baseline_completion=d(-10), planned_completion=d(-10), closed_at=d(-5),
                  deviations=[D.Deviation("L-D1", "other", 7, 7, d(-5), "x", "late_close")])
        done = replace(late, id="C", deviations=[replace(late.deviations[0], confirmed=True, confirmed_at=d(-4))])
        old = replace(late, id="O", closed_at=d(-40), baseline_completion=d(-50), planned_completion=d(-50))
        assert [o.id for o in D.closed_late_unconfirmed([late, done, old], T, S)] == ["L"]
