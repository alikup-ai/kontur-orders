"""Демо-данные (согласованность, сценарии) и хранилище (FR-16, NFR-04), v1.2."""
import json
from datetime import date, timedelta

from kontur import demo_data, storage
from kontur import domain as D

T = date(2026, 10, 17)
S = D.Settings()


def by_id():
    return {o.id: (o, D.evaluate(o, T, S)) for o in demo_data.build(T)}


def test_demo_size_unique_ids_and_consistency():
    orders = demo_data.build(T)
    assert 15 <= len(orders) <= 25 and len(orders) == 24
    assert len({o.id for o in orders}) == len(orders)
    ids = {o.id for o in orders}
    for o in orders:
        assert D.validate_order(o) == [], o.id
        assert o.status_updated_at <= T and o.created_at <= T
        assert o.stage_history[0].entered == o.created_at, o.id
        if o.is_closed:
            assert o.closed_at <= T and o.stage_history[-1].left == o.closed_at
        if o.order_type == "complaint":
            assert o.parent_order_id in ids
        for d in o.deviations:
            assert d.detected_at <= T and o.created_at <= d.detected_at


def test_demo_covers_channels_stages_types():
    orders = demo_data.build(T)
    assert {o.channel for o in orders} == set(D.CHANNELS)
    assert {o.stage for o in orders} == set(D.STAGES)
    assert {o.order_type for o in orders} == set(D.ORDER_TYPES)


def test_required_scenarios():
    m = by_id()
    o, e = m["KZ-26-102"]
    assert e.primary == D.ST_OVERDUE and D.latest_deviation(o).reason == "measure_error"
    assert [v.stage for v in o.stage_history] == [1, 2, 3, 4, 3] and len(o.deviations) == 2
    o, e = m["KZ-26-103"]
    assert e.primary == D.ST_RISK and o.deviations[-1].reason == "design_reapproval"
    o, e = m["KZ-26-104"]
    assert e.states == [D.ST_BLOCKED] and o.deviation(o.block_deviation_id).reason == "material_shortage"
    assert o.next_action_owner != o.stage_owner
    assert {"precontract", "no_manager", "no_stage_owner"} <= set(m["KZ-26-105"][1].flags)
    assert {"no_next_action", "no_next_owner"} <= set(m["KZ-26-106"][1].flags)
    assert {"stale", "baseline_unverified"} <= set(m["KZ-26-107"][1].flags)
    assert m["KZ-26-108"][1].finance.plan_pct > 40 and m["KZ-26-108"][0].deviations[0].confirmed
    assert "action_after_deadline" in m["KZ-26-109"][1].flags
    assert m["KZ-26-101"][1].flags == [] and m["KZ-26-110"][1].flags == []
    assert m["KZ-26-111"][1].flags == []
    assert "closed_late" in m["KZ-26-112"][1].flags and m["KZ-26-112"][0].deviations[-1].trigger == "late_close"
    assert len(set(m["KZ-26-114"][1].states)) == 3 and "low_margin" not in m["KZ-26-114"][1].flags
    assert m["KZ-26-115"][1].flags == ["deadline_moved"]
    assert m["KZ-26-116"][0].planned_completion == T and m["KZ-26-116"][1].primary == D.ST_RISK
    assert "low_margin" in m["KZ-26-121"][1].flags
    assert {"closed_late", "baseline_unverified"} <= set(m["KZ-26-122"][1].flags)
    assert m["KZ-26-123"][1].flags == ["precontract"]
    comp = m["KZ-26-124-R1"][0]
    assert comp.order_type == "complaint" and m["KZ-26-124"][0].deviations[-1].trigger == "complaint"


def test_demo_dates_relative_to_reset_day():
    later = T + timedelta(days=30)
    o = {x.id: x for x in demo_data.build(later)}["KZ-26-102"]
    assert D.evaluate(o, later, S).primary == D.ST_OVERDUE


def test_seed_audit_consistent_with_orders():
    m = by_id()
    entries = demo_data.seed_audit(T)
    for e in entries:
        o = m[e["order_id"]][0]
        if e["field"] == "planned_completion":
            assert e["new"] == o.planned_completion.isoformat()
        if e["field"] == "stage":
            assert e["new"] == o.stage
    total_devs = sum(len(o.deviations) for o, _ in m.values())
    assert sum(1 for e in entries if e["field"] == "deviation") == total_devs


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    st, warn = storage.load(T, p)
    assert warn is None and p.exists() and len(st.orders) == 24
    o = st.get("KZ-26-101")
    r = D.apply_changes(o, {}, today=T, user="u",
                        deviation={"reason": "other", "origin_stage": 2, "comment": "проверка"})
    st.replace_order(r.order, r.audit)
    st.snapshots.append(D.make_snapshot(D.compute_kpi(st.orders, T, st.settings), T, "u"))
    storage.save(st, p)
    st2, _ = storage.load(T, p)
    o2 = st2.get("KZ-26-101")
    assert o2.deviations[-1].comment == "проверка" and o2.stage_history == o.stage_history
    assert o2 == r.order and len(st2.snapshots) == 1
    assert not list(tmp_path.glob(".kontur_*.tmp"))


def test_reset_restores_demo(tmp_path):
    p = tmp_path / "s.json"
    st, _ = storage.load(T, p)
    st.orders = st.orders[:1]
    st.snapshots.append({"x": 1})
    storage.save(st, p)
    storage.reset(T, p)
    st2, _ = storage.load(T, p)
    assert len(st2.orders) == 24 and st2.snapshots == []


def test_corrupted_file_is_backed_up(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{битый json", encoding="utf-8")
    st, warn = storage.load(T, p)
    assert warn and len(st.orders) == 24
    assert (tmp_path / "s.broken.json").read_text(encoding="utf-8") == "{битый json"


def test_old_schema_is_backed_up_not_lost(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"version": 1, "orders": []}), encoding="utf-8")
    _, warn = storage.load(T, p)
    assert warn and "версия схемы 1" in warn and (tmp_path / "s.broken.json").exists()


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "s.json"
    d = storage.demo_state(T).to_dict()
    d["orders"].append(d["orders"][0])
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    _, warn = storage.load(T, p)
    assert warn and "Дубликаты" in warn


def test_add_order_rejects_duplicate():
    st = storage.demo_state(T)
    try:
        st.add_order(st.orders[0])
    except ValueError:
        return
    raise AssertionError("дубликат ID принят")
