"""«Контур заказов» — панель операционного управления заказами (MVP v1.2).

Запуск: streamlit run app.py
Вся бизнес-логика — в kontur/domain.py; здесь только интерфейс.

Подача (v1.3): экран строится как набор экспонатов. В заголовке каждого — вывод из данных,
под ним — что именно нарисовано, и только потом детализация числами. Главный экран отвечает
на три вопроса подряд: что горит по срокам, где стоят заказы, где теряется управляемость.
Графики — явные спецификации Vega-Lite 5: Altair 6 отдаёт схему v6, а Streamlit 1.66 несёт
рендерер v5, поэтому спецификации пишутся руками. Поля в данных графиков — латиницей:
выражения Vega не работают с кириллическими идентификаторами.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from kontur import domain as D
from kontur import storage
from kontur.demo_data import SCENARIOS, STAFF

st.set_page_config(page_title="Контур заказов · ДЕМО", page_icon="📋", layout="wide",
                   initial_sidebar_state="expanded")

# Дату расчёта можно зафиксировать для тестов: KONTUR_TODAY=2026-10-17
TODAY = date.fromisoformat(os.environ["KONTUR_TODAY"]) if os.environ.get("KONTUR_TODAY") else date.today()

PAGES = ["Требуют вмешательства", "Панель руководителя", "Реестр заказов",
         "Карточка заказа", "Журнал изменений", "Правила"]
PAGE_NAV = {
    "Требуют вмешательства": (":material/priority_high:", "Сегодня"),
    "Панель руководителя": (":material/monitoring:", "Неделя"),
    "Реестр заказов": (":material/table_rows:", "Реестр"),
    "Карточка заказа": (":material/description:", "Карточка"),
    "Журнал изменений": (":material/history:", "Журнал"),
    "Правила": (":material/rule:", "Правила"),
}
PAGE_LEAD = {
    "Требуют вмешательства": "Что горит сегодня, где стоят заказы и где теряется управляемость. "
                             "Внизу — поимённый список с исполнителем и сроком.",
    "Панель руководителя": "Итоги недели: срывы, их причины и плановая экономика. "
                           "У каждого числа есть знаменатель и правило расчёта — значок «?».",
    "Реестр заказов": "Все заказы одной таблицей, худшие сверху. Строка открывает карточку.",
    "Карточка заказа": "Один заказ целиком: ответственность, сроки, экономика, отклонения, изменения.",
    "Журнал изменений": "Кто и что менял, со старым и новым значением.",
    "Правила": "Как считается каждое состояние и показатель, и чего MVP не делает.",
}
STATE_BADGE = {D.ST_OVERDUE: ("red", ":material/error:"), D.ST_BLOCKED: ("orange", ":material/block:"),
               D.ST_RISK: ("yellow", ":material/warning:"), D.ST_OK: ("green", ":material/check_circle:"),
               D.ST_DONE: ("gray", ":material/task_alt:")}
TONE = {D.ST_OVERDUE: "red", D.ST_BLOCKED: "orange", D.ST_RISK: "amber", D.ST_OK: "green", D.ST_DONE: "grey"}
NO_REASON = ""

# Палитра графиков: один тёмно-синий как основной, остальное — только сигнал.
INK, TEXT_C, MUTED_C, SOFT_C = "#0B2A4A", "#16212E", "#5A6673", "#C9D4DF"
RED, ORANGE, AMBER, GREEN = "#C8102E", "#C2620F", "#C9A227", "#1C6B45"
GRID_C = "#EEF1F4"
STATE_ORDER = [D.STATES[s] for s in (D.ST_OVERDUE, D.ST_BLOCKED, D.ST_RISK, D.ST_OK)]
STATE_RANGE = [RED, ORANGE, AMBER, GREEN]
# Доска сдач: цвет карточки — состояние заказа, та же шкала, что у бейджей и списка.
BOARD_TONE = {D.ST_OVERDUE: "red", D.ST_BLOCKED: "orange", D.ST_RISK: "amber", D.ST_OK: "green"}
FONT = "'Source Sans 3', 'Source Sans Pro', -apple-system, Segoe UI, sans-serif"
# Признаки, которыми экран «где теряется управляемость» объясняет риск (блокировка и просрочка
# показаны отдельными экспонатами, поэтому здесь их нет).
GAP_FLAGS = ["no_next_owner", "no_next_action", "no_stage_owner", "no_manager",
             "next_action_overdue", "action_after_deadline", "stale", "deadline_soon", "low_margin"]

CSS = """
:root{
  --ink:#0B2A4A; --ink-d:#07203A; --text:#16212E; --muted:#5A6673; --line:#E4E7EB; --soft:#F6F8FA;
  --red:#C8102E; --orange:#C2620F; --amber:#8A6400; --green:#1C6B45; --grey:#6B7785;
}
[data-testid="stMetricValue"], [data-testid="stDataFrame"]{ font-variant-numeric:tabular-nums; }
/* 4rem сверху — под собственной шапкой Streamlit: в облаке она занимает ~60 px
   и перекрывала фирменную плашку. Локально шапка пустая, но отступ не мешает. */
.stMain .block-container{ padding-top:4rem; padding-bottom:3rem; max-width:1540px; }

/* st.header → h2 (заголовок экрана), st.subheader → h3 (раздел внутри экрана) */
h1, h2{ font-size:1.45rem !important; font-weight:700 !important; letter-spacing:-.015em;
        color:var(--ink) !important; margin:0 0 .1rem 0 !important; padding:0 !important; }
h3{ font-size:.95rem !important; font-weight:700 !important; color:var(--ink) !important;
    margin:1.5rem 0 .6rem 0 !important; padding:0 0 .35rem 0 !important;
    border-bottom:1px solid var(--line); }

/* ---------------------------------------------------------------- шапка */
.k-top{ display:flex; align-items:center; justify-content:space-between; gap:1rem;
        background:var(--ink-d); color:#fff; padding:.6rem .95rem; border-radius:3px; margin-bottom:.55rem; }
.k-top .b{ font-size:1rem; font-weight:700; letter-spacing:.04em; }
.k-top .b i{ font-style:normal; font-weight:400; opacity:.72; letter-spacing:.02em;
             font-size:.8rem; margin-left:.6rem; }
.k-top .d{ font-size:.78rem; text-align:right; opacity:.8; letter-spacing:.04em; text-transform:uppercase; }
.k-top .d b{ display:block; font-size:.98rem; letter-spacing:0; text-transform:none; opacity:1; }

/* ---------------------------------------------------------------- навигация */
.st-key-topnav{ border-bottom:2px solid var(--line); margin:0 0 1rem 0; }
.st-key-topnav [data-testid^="stBaseButton"]{
  width:100%; border:none !important; border-radius:0 !important; background:transparent !important;
  font-weight:600 !important; font-size:.88rem !important; padding:.45rem .3rem !important;
  color:var(--muted) !important; box-shadow:none !important;
}
.st-key-topnav [data-testid^="stBaseButton"]:hover{ color:var(--ink) !important; background:var(--soft) !important; }
.st-key-topnav [data-testid="stBaseButton-primary"]{
  color:var(--ink) !important; box-shadow:inset 0 -3px 0 var(--ink) !important;
}

/* ---------------------------------------------------------------- вывод и экспонаты */
.k-lead{ color:var(--muted); font-size:.9rem; margin:.1rem 0 .8rem 0; }
.k-hero{ font-size:1.08rem; line-height:1.55; color:var(--text); background:var(--soft);
         border-left:3px solid var(--ink); padding:.65rem .9rem; margin:.1rem 0 1rem 0;
         border-radius:0 3px 3px 0; }
.k-hero b{ color:var(--ink); font-weight:700; }
.k-hero .r{ color:var(--red); font-weight:700; }
.k-hero .o{ color:var(--orange); font-weight:700; }

.k-ex-n{ font-size:.66rem; font-weight:700; letter-spacing:.14em; color:var(--muted);
         text-transform:uppercase; }
.k-ex-t{ font-size:1.02rem; font-weight:700; line-height:1.35; color:var(--ink); margin:.1rem 0 .15rem; }
.k-board{ display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:.55rem;
          margin:.35rem 0 .2rem; align-items:start; }
.k-col-h{ display:flex; align-items:flex-start; justify-content:space-between; gap:.3rem;
          border-bottom:2px solid var(--line); padding-bottom:.3rem; margin-bottom:.45rem; }
.k-col-h s{ text-decoration:none; font-size:.66rem; font-weight:700; letter-spacing:.06em;
            text-transform:uppercase; color:var(--muted); display:block; line-height:1.25; }
.k-col-h em{ font-style:normal; font-size:.65rem; color:var(--muted); font-weight:600; }
.k-col-h b{ font-size:1.2rem; font-weight:700; color:var(--ink); line-height:1; }
.k-col-h.hot b{ color:var(--red); }
.k-card{ border:1px solid var(--line); border-left:4px solid var(--grey); border-radius:3px;
         padding:.32rem .5rem .36rem; margin-bottom:.35rem; background:#fff; }
.k-card b{ font-size:.81rem; font-weight:700; color:var(--ink); display:block; line-height:1.3; }
.k-card span{ font-size:.74rem; color:var(--text); }
.k-card span u{ text-decoration:none; color:var(--muted); }
.k-card i{ display:block; font-style:normal; font-size:.69rem; color:var(--muted);
           white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.k-card.red{ border-left-color:var(--red); } .k-card.orange{ border-left-color:var(--orange); }
.k-card.amber{ border-left-color:var(--amber); } .k-card.green{ border-left-color:var(--green); }
.k-col-empty{ font-size:.71rem; color:var(--muted); padding:.25rem .1rem; }
@media (max-width:1250px){ .k-board{ grid-template-columns:repeat(3, minmax(0,1fr)); } }
@media (max-width:700px){ .k-board{ grid-template-columns:repeat(2, minmax(0,1fr)); } }
.k-keys{ display:flex; gap:1.1rem; flex-wrap:wrap; font-size:.78rem; color:var(--muted);
         margin:-.2rem 0 .1rem .2rem; }
.k-keys i{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px;
           vertical-align:middle; }
.k-ex-s{ font-size:.79rem; line-height:1.4; color:var(--muted); margin-bottom:.3rem; }
div[class*="st-key-ex-"]{ border-color:var(--line) !important; border-radius:3px !important;
                          padding:.75rem .9rem .35rem .9rem !important; background:#fff; }

/* ---------------------------------------------------------------- плитки показателей */
[data-testid="stMetric"]{
  background:#fff; border:1px solid var(--line); border-top:3px solid var(--grey);
  border-radius:3px; padding:.55rem .8rem .45rem .8rem;
}
[data-testid="stMetricLabel"] p{
  font-size:.73rem !important; font-weight:700 !important; color:var(--muted) !important;
  text-transform:uppercase; letter-spacing:.045em; line-height:1.25;
}
[data-testid="stMetricValue"]{ font-size:1.9rem !important; font-weight:700 !important; color:var(--ink) !important; }
div[class*="st-key-kpi-red"]    [data-testid="stMetric"]{ border-top-color:var(--red); }
div[class*="st-key-kpi-orange"] [data-testid="stMetric"]{ border-top-color:var(--orange); }
div[class*="st-key-kpi-amber"]  [data-testid="stMetric"]{ border-top-color:var(--amber); }
div[class*="st-key-kpi-green"]  [data-testid="stMetric"]{ border-top-color:var(--green); }
div[class*="st-key-kpi-ink"]    [data-testid="stMetric"]{ border-top-color:var(--ink); }
div[class*="st-key-kpi-"] [data-testid="stCaptionContainer"] p{ font-size:.75rem !important; line-height:1.35; }

/* ---------------------------------------------------------------- карточки заказов */
div[class*="st-key-card-"]{ border-radius:3px !important; }
div[class*="st-key-card-red"]{    box-shadow:inset 4px 0 0 var(--red) !important; }
div[class*="st-key-card-orange"]{ box-shadow:inset 4px 0 0 var(--orange) !important; }
div[class*="st-key-card-amber"]{  box-shadow:inset 4px 0 0 var(--amber) !important; }
div[class*="st-key-card-green"]{  box-shadow:inset 4px 0 0 var(--green) !important; }
div[class*="st-key-card-grey"]{   box-shadow:inset 4px 0 0 var(--grey) !important; }

.k-lab{ font-size:.66rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase;
        color:var(--muted); display:block; margin-bottom:-.1rem; }
.k-id{ font-size:1rem; font-weight:700; color:var(--ink); }
.k-do{ font-size:.97rem; font-weight:600; color:var(--text); }
.k-who{ font-size:.92rem; color:var(--text); }
.k-none{ color:var(--red); font-weight:600; }

/* ---------------------------------------------------------------- чипы фильтра списка */
.st-key-sevbar [data-testid^="stBaseButton"]{
  width:100%; border-radius:999px !important; font-size:.83rem !important; font-weight:600 !important;
  padding:.28rem .6rem !important; border:1px solid var(--line) !important; box-shadow:none !important;
}
.st-key-sevbar [data-testid="stBaseButton-primary"]{
  background:var(--ink) !important; color:#fff !important; border-color:var(--ink) !important;
}
.st-key-sevbar [data-testid="stBaseButton-secondary"]{ background:#fff !important; color:var(--muted) !important; }
.st-key-sevbar [data-testid="stBaseButton-secondary"]:hover{ color:var(--ink) !important; background:var(--soft) !important; }

/* ---------------------------------------------------------------- прочее */
[data-testid="stSidebar"]{ background:var(--soft); border-right:1px solid var(--line); }
[data-testid="stSidebar"] .block-container{ padding-top:1.1rem; }
.k-brand{ font-size:.92rem; font-weight:700; letter-spacing:.02em; color:var(--ink); line-height:1.2; }
.k-brand span{ display:block; font-size:.7rem; font-weight:600; letter-spacing:.06em;
               text-transform:uppercase; color:var(--muted); margin-top:.15rem; }
[data-testid="stAlert"]{ border-radius:3px; font-size:.82rem; padding:.4rem .7rem; }
[data-testid="stExpander"] summary{ font-size:.83rem; font-weight:600; color:var(--muted); }
[data-testid="stExpander"] details{ border-color:var(--line); }
hr{ margin:.6rem 0 !important; border-color:var(--line) !important; }
"""
st.html(f"<style>{CSS}</style>")


# ---------------------------------------------------------------- форматирование

def money(v) -> str:
    return "—" if v is None else f"{v:,.0f} ₽".replace(",", " ")


def pct(v) -> str:
    return "не определена" if v is None else f"{v:.1f} %"


def dt(v) -> str:
    return "—" if v is None else v.strftime("%d.%m.%Y")


def share(m: D.Metric) -> str:
    return f"{m.numerator} из {m.denominator}" + ("" if m.pct is None else f" · {m.pct:.0f} %")


def of(m: D.Metric) -> str:
    """Подпись под показателем: знаменатель и доля."""
    return f"из {m.denominator}" + ("" if m.pct is None else f" · {m.pct:.0f} %")


def badge(state: str) -> str:
    color, icon = STATE_BADGE[state]
    return f":{color}-badge[{icon} {D.STATES[state]}]"


def due_text(d: date | None) -> str:
    if d is None:
        return "срок не задан"
    n = (d - TODAY).days
    if n < 0:
        return f"{dt(d)} · просрочено на {-n} дн."
    return f"{dt(d)} · сегодня" if n == 0 else f"{dt(d)} · через {n} дн."


def flag_text(ev: D.Evaluation, kinds=("ops", "fin", "info")) -> str:
    out = []
    for f in ev.flags:
        if D.FLAGS[f][0] not in kinds or f == "blocked":
            continue
        label = D.FLAGS[f][1]
        if f == "deadline_moved":
            label += f" на {ev.deadline_shift_days} дн."
        if f == "closed_late":
            label += f" на {ev.days_overdue} дн."  # QA D20
        out.append(label)
    return " · ".join(out)


def audit_value(fld: str, v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if fld == "stage":
        return f"{v}. {D.STAGES.get(int(v), v)}"
    if fld == "deviation":
        return D.REASONS.get(v, v)
    if fld in D.MONEY_FIELDS:
        return money(float(v))
    if fld in D.ORDER_DATE_FIELDS:
        try:
            return dt(date.fromisoformat(v))
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def audit_df(entries: list[dict], with_order: bool) -> pd.DataFrame:
    return pd.DataFrame([{"Когда": e["ts"].replace("T", " "), **({"Заказ": e["order_id"]} if with_order else {}),
                          "Кто": e["user"], "Что": e["field_label"],
                          "Было": audit_value(e["field"], e["old"]), "Стало": audit_value(e["field"], e["new"]),
                          "Комментарий": e["comment"]} for e in reversed(entries)])


def open_order(oid: str) -> None:
    st.session_state.page = "Карточка заказа"
    st.session_state.selected_id = oid


def goto(page: str) -> None:
    st.session_state.page = page


def pick_sev(v: str) -> None:
    st.session_state.sev = v


def plu(n: int, one: str, few: str, many: str) -> str:
    """Согласование с числом: 1 заказ, 2 заказа, 5 заказов. Выводы собираются из данных,
    поэтому форма слова выбирается по числу, а не зашивается в текст."""
    n100, n10 = abs(n) % 100, abs(n) % 10
    if 11 <= n100 <= 14:
        return many
    if n10 == 1:
        return one
    if 2 <= n10 <= 4:
        return few
    return many


def orders_word(n: int) -> str:
    return f"{n} {plu(n, 'заказ', 'заказа', 'заказов')}"


def lead(text: str) -> None:
    st.markdown(f"<div class='k-lead'>{text}</div>", unsafe_allow_html=True)


def hero(text: str) -> None:
    """Вывод экрана одной строкой — то, что читают первым."""
    st.markdown(f"<div class='k-hero'>{text}</div>", unsafe_allow_html=True)


def exhibit(n: str, insight: str, sub: str) -> None:
    """Заголовок экспоната: вывод из данных, под ним — что нарисовано."""
    st.markdown(f"<div class='k-ex-n'>Рис. {n}</div><div class='k-ex-t'>{insight}</div>"
                f"<div class='k-ex-s'>{sub}</div>", unsafe_allow_html=True)


def kpi(col, slug: str, label: str, value, sub: str | None = None, help: str | None = None) -> None:
    """Плитка показателя. slug задаёт цвет верхней полосы: kpi-red / orange / amber / green / ink."""
    with col.container(key=slug):
        st.metric(label, value, help=help)
        if sub:
            st.caption(sub)


# ---------------------------------------------------------------- графики (Vega-Lite 5)

def _y(limit: int = 300) -> dict:
    return {"field": "cat", "type": "nominal", "sort": None,
            "axis": {"title": None, "labelFontSize": 12, "labelColor": TEXT_C, "labelLimit": limit,
                     "domain": False, "ticks": False, "labelPadding": 6}}


def _show(spec: dict, height: int) -> None:
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "height": height,
            "padding": {"left": 0, "top": 2, "right": 28, "bottom": 2},
            "config": {"font": FONT, "background": "transparent", "view": {"stroke": None},
                       "axis": {"grid": False}, "legend": {"labelFontSize": 12, "labelColor": TEXT_C}},
            **spec}
    st.vega_lite_chart(spec, width="stretch", theme=None)


def chart_bars(rows: list[dict], color: str = INK, part: bool = False, fmt: str | None = None,
               labels: int = 320) -> None:
    """Горизонтальные столбики. part=True — светлый столбик «всего» с тёмной вложенной долей
    (подтверждённые ⊂ все), поэтому доли не складываются. fmt — поле подписи вместо значения."""
    if not rows:
        st.caption("Нет данных.")
        return
    y, x = _y(labels), {"field": "val", "type": "quantitative", "axis": None}
    layers = [{"mark": {"type": "bar", "height": 14, "color": SOFT_C if part else color},
               "encoding": {"y": y, "x": x}}]
    if part:
        layers.append({"mark": {"type": "bar", "height": 14, "color": color},
                       "encoding": {"y": y, "x": {"field": "part", "type": "quantitative", "axis": None}}})
    text = {"field": fmt, "type": "nominal"} if fmt else {"field": "val", "type": "quantitative"}
    layers.append({"mark": {"type": "text", "align": "left", "dx": 6, "fontSize": 12,
                            "fontWeight": 600, "color": TEXT_C},
                   "encoding": {"y": y, "x": x, "text": text}})
    _show({"data": {"values": rows}, "layer": layers}, max(70, 26 * len(rows)))


def chart_bars_by_state(rows: list[dict], color_field: str = "state", labels: int = 320) -> None:
    """Столбики, окрашенные состоянием заказа (одна шкала цвета на весь интерфейс)."""
    y, x = _y(labels), {"field": "val", "type": "quantitative", "axis": None}
    color = {"field": color_field, "type": "nominal",
             "scale": {"domain": STATE_ORDER, "range": STATE_RANGE},
             "legend": {"orient": "top", "direction": "horizontal", "title": None,
                        "symbolType": "square", "offset": 2}}
    layers = [{"mark": {"type": "bar", "height": 14}, "encoding": {"y": y, "x": x, "color": color}},
              {"mark": {"type": "text", "align": "left", "dx": 6, "fontSize": 12, "fontWeight": 600,
                        "color": TEXT_C},
               "encoding": {"y": y, "x": x, "text": {"field": "val", "type": "quantitative"}}}]
    _show({"data": {"values": rows}, "layer": layers}, max(70, 26 * len(rows)))


# ---------------------------------------------------------------- состояние и боковая панель

state, load_warning = storage.load(TODAY)
S = state.settings
st.session_state.setdefault("page", PAGES[0])
st.session_state.setdefault("sev", "all")

with st.sidebar:
    st.markdown("<div class='k-brand'>📋 КОНТУР ЗАКАЗОВ<span>Операционное управление</span></div>",
                unsafe_allow_html=True)
    st.warning("Синтетические демонстрационные данные. Не являются показателями компании.",
               icon=":material/science:")
    # Навигация — в основной области; здесь тот же переключатель как резервный и для клавиатуры.
    with st.expander("Разделы"):
        st.radio("Раздел", PAGES, key="page", label_visibility="collapsed")
    st.selectbox("Кто вносит изменения", STAFF, key="user",
                 help="Авторизации нет: имя выбирается вручную и не проверяется.")
    st.divider()
    st.markdown("**Фильтры**")
    people = sorted({p for o in state.orders for p in (o.manager, o.stage_owner, o.next_action_owner) if p})
    f_people = st.multiselect("Ответственный", people, placeholder="Все",
                              help="Менеджер заказа, ответственный за стадию или исполнитель действия")
    f_channels = st.multiselect("Канал продаж", list(D.CHANNELS), format_func=D.CHANNELS.get,
                                placeholder="Все")
    st.divider()
    with st.expander("Сброс демо-данных"):
        st.caption("Восстанавливает исходные 24 заказа с датами от сегодняшнего дня; "
                   "журнал и снимки очищаются.")
        confirm = st.checkbox("Подтверждаю сброс", key="confirm_reset")
        if st.button("Сбросить", disabled=not confirm, key="reset_btn"):
            storage.reset(TODAY)
            st.session_state.confirm_reset = False
            st.session_state.flash = "Демо-данные восстановлены"
            st.rerun()

page = st.session_state.page

st.markdown(f"<div class='k-top'><div class='b'>КОНТУР ЗАКАЗОВ"
            f"<i> операционное управление заказами · демонстрация</i></div>"
            f"<div class='d'>дата расчёта<b>{dt(TODAY)}</b></div></div>", unsafe_allow_html=True)

# QA D16: метка в основной области — видна при свёрнутой боковой панели, на телефоне и на скриншоте.
st.warning(f"**Демонстрация на синтетических данных** (набор от {state.generated_for}). "
           "Числа ниже — не показатели компании.", icon=":material/science:")
if load_warning:
    st.error(load_warning)
if msg := st.session_state.pop("flash", None):
    st.toast(msg, icon=":material/check:")

with st.container(key="topnav"):
    nav = st.columns(len(PAGES), gap=None)
    for col, p in zip(nav, PAGES):
        icon, short = PAGE_NAV[p]
        col.button(short, key=f"nav_{p}", on_click=goto, args=(p,), icon=icon,
                   type="primary" if p == page else "tertiary", width="stretch")

filtered = D.filter_orders(state.orders, people=f_people, channels=f_channels)
filter_on = bool(f_people or f_channels)
evals = {o.id: D.evaluate(o, TODAY, S) for o in state.orders}


def persist(msg: str) -> None:
    storage.save(state)
    st.session_state.flash = msg
    st.rerun()


def filter_note() -> None:
    if filter_on:
        st.info(f"Применены фильтры: {len(filtered)} из {len(state.orders)} заказов. "
                "Показатели пересчитаны по отфильтрованным заказам.", icon=":material/filter_alt:")


def order_card(o: D.Order, ev: D.Evaluation) -> None:
    """Карточка в списке: слева — что за заказ, в центре — следующий шаг и кто его делает."""
    with st.container(border=True, key=f"card-{TONE[ev.primary]}-{o.id}"):
        c1, c2, c3, c4 = st.columns([3, 2.6, 4.2, 1.2], vertical_alignment="center")
        kind = " · рекламация" if o.order_type == "complaint" else ""
        c1.markdown(f"<span class='k-id'>{o.id}</span> · {o.client}", unsafe_allow_html=True)
        c1.caption(f"{D.CHANNELS[o.channel]} · {o.sales_point}{kind}  \n"
                   f"Стадия {o.stage}/7: {D.STAGES[o.stage]}  \n"
                   f"Срок заказа: {due_text(o.planned_completion) if o.has_contract else 'договор не подписан'}")
        c2.markdown(" ".join(badge(s) for s in ev.states))
        if text := flag_text(ev):
            c2.caption(text)
        who = o.next_action_owner or "<span class='k-none'>исполнитель не назначен</span>"
        act = o.next_action or "<span class='k-none'>не определено</span>"
        c3.markdown(f"<span class='k-lab'>Дальше</span><span class='k-do'>{act}</span><br>"
                    f"<span class='k-lab'>Кто и к какому сроку</span>"
                    f"<span class='k-who'>{who} · {due_text(o.next_action_due)}</span>",
                    unsafe_allow_html=True)
        latest = D.latest_deviation(o)
        reason = ""
        if latest:
            mark = "подтверждена" if latest.confirmed else "не подтверждена"
            reason = f"  \nПричина: {D.REASONS[latest.reason]} (стадия возникновения {latest.origin_stage}; {mark})"
        c3.caption(f"Отв. за стадию: {o.stage_owner or 'не назначен'} · Менеджер: {o.manager or 'не назначен'}"
                   f"{reason}")
        c4.button("Открыть", key=f"open_{o.id}", on_click=open_order, args=(o.id,), width="stretch")


def deviation_inputs(prefix: str, origin_max: int, label: str) -> dict:
    """Поля отклонения внутри формы. Пустая причина = отклонение не добавляется."""
    st.markdown(f"**{label}**")
    a, b = st.columns(2)
    reason = a.selectbox("Причина", [NO_REASON] + list(D.REASONS), key=f"{prefix}_reason",
                         format_func=lambda r: D.REASONS.get(r, "— не добавлять —"))
    origin = b.selectbox("Стадия возникновения", list(range(1, origin_max + 1)), index=origin_max - 1,
                         key=f"{prefix}_origin", format_func=lambda s: f"{s}. {D.STAGES[s]}",
                         help="Где ошибка возникла, а не где её обнаружили")
    comment = st.text_input("Что произошло", key=f"{prefix}_comment")
    return {"reason": reason, "origin_stage": origin, "comment": comment}


def show_errors(errors: list[str]) -> None:
    for e in errors:
        st.error(e)


# ---------------------------------------------------------------- страницы

if page == "Требуют вмешательства":
    st.header("Что требует вмешательства сегодня")
    lead(PAGE_LEAD[page])
    filter_note()

    items = D.attention_list(filtered, TODAY, S)
    active = [o for o in filtered if not o.is_closed]
    active_n = len(active)
    late = D.closed_late_unconfirmed(filtered, TODAY, S)
    groups = [("Просрочены", D.ST_OVERDUE), ("Заблокированы", D.ST_BLOCKED), ("Под риском", D.ST_RISK),
              ("Плановая маржа ниже порога (операционно в норме)", D.ST_OK)]
    by_state = {stt: [(o, ev) for o, ev in items if ev.primary == stt] for _, stt in groups}
    n_over, n_block = len(by_state[D.ST_OVERDUE]), len(by_state[D.ST_BLOCKED])
    n_risk, n_low = len(by_state[D.ST_RISK]), len(by_state[D.ST_OK])

    if items:
        parts = []
        if n_over:
            parts.append(f"<span class='r'>{n_over} просрочено</span>")
        if n_block:
            parts.append(f"<span class='o'>{n_block} заблокировано</span>")
        if n_risk:
            parts.append(f"{n_risk} под риском")
        if n_low:
            parts.append(f"{n_low} с маржой ниже порога")
        tail = (f" Плюс закрытых с нарушением срока без подтверждённой причины: <b>{len(late)}</b>."
                if late else "")
        hero(f"<b>{len(items)} из {active_n}</b> активных заказов требуют вмешательства: "
             + ", ".join(parts) + "." + tail)
    else:
        hero(f"По текущим фильтрам вмешательство не требуется: все {active_n} активных заказов в норме.")

    # ---------- Рис. 1: календарь сдач по неделям
    with st.container(border=True, key="ex-board"):
        # Недели календарные: фабрика планирует «что сдаём на этой неделе», а не скользящим окном.
        w1 = TODAY + timedelta(days=6 - TODAY.weekday())        # воскресенье текущей недели
        w2, w3 = w1 + timedelta(days=7), w1 + timedelta(days=14)
        cols = [
            ("Просрочено", "срок уже прошёл", lambda d: d is not None and d < TODAY),
            ("Эта неделя", f"по {dt(w1)[:5]}", lambda d: d is not None and TODAY <= d <= w1),
            ("Следующая неделя", f"{dt(w1 + timedelta(days=1))[:5]}–{dt(w2)[:5]}",
             lambda d: d is not None and w1 < d <= w2),
            ("Через две недели", f"{dt(w2 + timedelta(days=1))[:5]}–{dt(w3)[:5]}",
             lambda d: d is not None and w2 < d <= w3),
            ("Позже", f"после {dt(w3)[:5]}", lambda d: d is not None and d > w3),
            ("Срок не задан", "договор не подписан", lambda d: d is None),
        ]
        buckets = []
        for title, sub, pred in cols:
            got = sorted((o for o in active if pred(o.planned_completion)),
                         key=lambda x: (x.planned_completion or date.max, x.id))
            buckets.append((title, sub, got))

        html = ["<div class='k-board'>"]
        for title, sub, got in buckets:
            if title == "Срок не задан" and not got:
                continue
            hot = " hot" if title == "Просрочено" and got else ""
            html.append(f"<div><div class='k-col-h{hot}'><div><s>{escape(title)}</s>"
                        f"<em>{escape(sub)}</em></div><b>{len(got)}</b></div>")
            if not got:
                html.append("<div class='k-col-empty'>пусто</div>")
            for o in got:
                ev = evals[o.id]
                d = o.planned_completion
                if d is None:
                    when = "срока нет"
                else:
                    n = (d - TODAY).days
                    when = "сегодня" if n == 0 else (f"+{n} дн." if n > 0 else f"−{-n} дн.")
                who = o.next_action_owner or "исполнитель не назначен"
                html.append(
                    f"<div class='k-card {BOARD_TONE[ev.primary]}'><b>{escape(o.id)}</b>"
                    f"<span>{o.stage}/{D.LAST_STAGE}<u> · </u>{escape(when)}</span>"
                    f"<i>{escape(who)}</i></div>")
            html.append("</div>")
        html.append("</div>")

        n_week = len(buckets[1][2])
        if n_over:
            ins = (f"Просрочено {orders_word(n_over)}; до конца недели сдавать ещё "
                   f"{orders_word(n_week)}.")
        elif n_week:
            ins = f"Просроченных нет; до конца недели сдавать {orders_word(n_week)}."
        else:
            ins = "Просроченных нет, и на этой неделе сдавать нечего."
        nxt = len(buckets[2][2])
        if nxt:
            ins += f" На следующей неделе — {nxt}."
        exhibit("1 · Календарь сдач", ins,
                "Активные заказы разложены по сроку сдачи. В карточке — номер, стадия из семи "
                "и запас до срока; цветная полоска слева — состояние заказа. Недели календарные, "
                "границы указаны под названием колонки.")
        st.html("".join(html))
        st.caption("Заказы без подписанного договора вынесены в отдельную колонку: срок им ещё "
                   "не задан, поэтому в недели их ставить не на чем.")
        with st.expander("Числами"):
            st.dataframe(pd.DataFrame([{
                "Когда сдавать": title, "Заказ": o.id, "Клиент / дилер": o.client,
                "Стадия": f"{o.stage}. {D.STAGES[o.stage]}", "Срок": o.planned_completion,
                "Состояние": D.STATES[evals[o.id].primary],
                "Исполнитель": o.next_action_owner or "—"}
                for title, _, got in buckets for o in got]), hide_index=True, width="stretch",
                column_config={"Срок": st.column_config.DateColumn(format="DD.MM.YYYY")})

    # ---------- Рис. 2: где теряется управляемость
    with st.container(border=True, key="ex-gaps"):
        gaps = []
        for f in GAP_FLAGS:
            n = sum(1 for o in active if f in evals[o.id].flags)
            if n:
                gaps.append({"cat": D.FLAGS[f][1], "val": n})
        gaps.sort(key=lambda r: -r["val"])
        ins = (f"Чаще всего мешает одно: «{gaps[0]['cat'].lower()}» — {orders_word(gaps[0]['val'])}."
               if gaps else "Признаков риска по активным заказам нет.")
        exhibit("2 · Где теряется управляемость", ins,
                "Сколько активных заказов задето каждым признаком риска. Один заказ попадает "
                "в несколько строк, поэтому сумма больше числа заказов.")
        chart_bars(gaps, labels=330)
        with st.expander("Числами"):
            st.dataframe(pd.DataFrame([{"Признак": r["cat"], "Заказов": r["val"]} for r in gaps]),
                         hide_index=True, width="stretch")

    # ---------- поимённый список
    st.markdown("<div class='k-ex-n' style='margin-top:1.4rem'>Список вмешательства</div>"
                "<div class='k-ex-t'>Кто делает следующий шаг по каждому заказу</div>",
                unsafe_allow_html=True)
    with st.container(key="sevbar"):
        chips = [("all", f"Все · {len(items)}")] + [
            (stt, f"{title.split(' (')[0]} · {len(by_state[stt])}") for title, stt in groups]
        cc = st.columns(len(chips) + 3, gap="small")
        for col, (val, label) in zip(cc, chips):
            col.button(label, key=f"sev_{val}", on_click=pick_sev, args=(val,), width="stretch",
                       type="primary" if st.session_state.sev == val else "secondary")
    sev = st.session_state.sev

    with st.expander("Как читается этот список"):
        st.caption(f"{len(items)} из {active_n} активных заказов имеют хотя бы один признак отклонения. "
                   "Группы — по **главному** состоянию заказа, поэтому числа могут быть меньше, чем на панели: там "
                   "заказ считается во всех своих состояниях. Внутри группы: просроченные — по дням просрочки, "
                   "остальные — по ближайшему сроку заказа. «Кто» — исполнитель следующего действия.")

    if not items:
        st.success("Нет заказов, требующих вмешательства, по текущим фильтрам.")
    for title, stt in groups:
        group = by_state[stt]
        if group and sev in ("all", stt):
            st.subheader(f"{title} — {len(group)}")
            for o, ev in group:
                order_card(o, ev)
    # QA D17: поздно закрытые за период без подтверждённой причины — тоже повестка совещания (B5).
    if late and sev == "all":
        st.subheader(f"Закрыты с нарушением срока — причина не подтверждена — {len(late)}")
        st.caption(f"Закрытые за последние {S.period_days} дн. позже первоначального срока, у которых последнее "
                   "отклонение не подтверждено на совещании.")
        for o in late:
            order_card(o, evals[o.id])

elif page == "Панель руководителя":
    st.header("Итоги недели")
    lead(PAGE_LEAD[page])
    filter_note()
    k = D.compute_kpi(filtered, TODAY, S)
    hero(f"Активных заказов <b>{k['active'].numerator}</b>, с договором <b>{share(k['contracted'])}</b>. "
         f"<span class='r'>Просрочено {k['overdue'].numerator}</span>, "
         f"<span class='o'>заблокировано {k['blocked'].numerator}</span>, "
         f"под риском {k['at_risk'].numerator}. За период {k['period']} закрыто с нарушением срока "
         f"<b>{share(k['closed_late'])}</b>, причина подтверждена у <b>{share(k['explained'])}</b> срывов.")

    st.subheader("Сейчас")
    c = st.columns(6)
    kpi(c[0], "kpi-ink-active", "Активных заказов", k["active"].numerator,
        sub=f"с договором: {share(k['contracted'])}", help=k["active"].rule)
    for col, key_, label, tone in ((c[1], "overdue", "Просрочено", "red"),
                                   (c[2], "at_risk", "Под риском (все)", "amber"),
                                   (c[3], "blocked", "Заблокировано", "orange"),
                                   (c[4], "ownership_gap", "Без владельца / шага", "amber"),
                                   (c[5], "fresh", "Статус обновлён ≤ 7 дн.", "green")):
        m = k[key_]
        kpi(col, f"kpi-{tone}-{key_}", label, m.numerator, sub=of(m), help=m.rule)
    st.caption("Доли — по **активным** заказам; просрочка — только по заказам с договором. "
               "Один заказ может входить в несколько показателей. Значок «?» — правило расчёта.")
    ob = k["ownership_breakdown"]
    st.caption("Разбивка «без владельца / шага»: " + " · ".join(
        f"{D.FLAGS[f][1].lower()}: {ob[f]}" for f in ob))

    st.subheader(f"За период {k['period']}")
    c = st.columns(5)
    cl = k["closed_late"]
    kpi(c[0], "kpi-red-closed_late", "Закрыто с нарушением срока", cl.numerator, help=cl.rule,
        sub=f"{of(cl)}  \nисключено (срок не сверен): {k['closed_late_excluded']}  \n"
            f"весь пилот: {share(k['closed_late_all'])}")
    ex = k["explained"]
    kpi(c[1], "kpi-ink-explained", "Срывы с подтверждённой причиной", ex.numerator, help=ex.rule,
        sub=f"{of(ex)}  \nпоследнее отклонение подтверждено на совещании")
    kpi(c[2], "kpi-amber-dev", "Отклонений", k["deviations_total"],
        sub=f"подтверждено: {k['deviations_confirmed']}")
    kpi(c[3], "kpi-orange-complaints", "Рекламаций", k["complaints"].numerator, help=k["complaints"].rule)
    bv = k["baseline_verified"]
    kpi(c[4], "kpi-green-baseline", "Первоначальный срок сверен", bv.numerator, help=bv.rule,
        sub=f"{of(bv)}  \nактивные с договором")

    # ---------- Рис. 4-5: причины срывов
    g_left, g_right = st.columns(2)
    with g_left, st.container(border=True, key="ex-reasons"):
        rows = [{"cat": D.REASONS[r], "val": a, "part": b}
                for r, (a, b) in sorted(k["dev_by_reason"].items(), key=lambda x: -x[1][0]) if a]
        ins = (f"Главная названная причина — «{rows[0]['cat'].lower()}»: {rows[0]['val']} из "
               f"{k['deviations_total']} отклонений за период."
               if rows else "За период отклонений не зафиксировано.")
        exhibit("3 · Причины", ins,
                "Отклонения за период по причинам. Светлый столбик — все, тёмный — подтверждённые "
                "на совещании. Выводы делаются только по подтверждённым.")
        chart_bars(rows, part=True, labels=300)
        with st.expander("Числами"):
            st.dataframe(pd.DataFrame([{"Причина": r["cat"], "Все": r["val"], "Подтверждённые": r["part"]}
                                       for r in rows]), hide_index=True, width="stretch")
        st.caption("Справочник причин предварительный и не подтверждает гипотезы без ретроспективы "
                   "(docs/04_coo_review.md, §3).")

    with g_right, st.container(border=True, key="ex-origin"):
        orows = [{"cat": f"{s}. {D.STAGES[s]}", "val": a, "part": b}
                 for s, (a, b) in k["dev_by_origin"].items()]
        worst = max(orows, key=lambda r: r["val"]) if orows else {"cat": "—", "val": 0}
        ins = (f"Больше всего ошибок рождается на стадии «{worst['cat'].split('. ', 1)[1]}» — "
               f"{worst['val']} {plu(worst['val'], 'отклонение', 'отклонения', 'отклонений')}."
               if worst["val"] else "За период отклонений не зафиксировано.")
        exhibit("4 · Откуда ошибки", ins,
                "Отклонения за период по стадии, на которой ошибка возникла, — а не по той, где её "
                "заметили. Включая закрытые заказы.")
        chart_bars(orows, part=True, labels=270)
        with st.expander("Числами"):
            st.dataframe(pd.DataFrame([{"Стадия возникновения": r["cat"], "Все": r["val"],
                                        "Подтверждённые": r["part"]} for r in orows]),
                         hide_index=True, width="stretch")

    # ---------- Рис. 6: плановая экономика
    with st.container(border=True, key="ex-margin"):
        mrows = []
        for o in sorted(filtered, key=lambda x: (D.finance(x).plan_pct is None, D.finance(x).plan_pct or 0)):
            f = D.finance(o)
            if o.is_closed or o.order_type != "main" or f.plan_pct is None:
                continue
            thr = S.margin_threshold(o.channel)
            below = f.plan_pct < thr
            mrows.append({"cat": f"{o.id} · {D.CHANNELS[o.channel].lower()}", "val": round(f.plan_pct, 1),
                          "lab": f"{f.plan_pct:.1f} %".replace(".", ","),
                          "state": D.STATES[D.ST_OVERDUE] if below else D.STATES[D.ST_OK]})
        low = k["low_margin_active"]
        ins = (f"{low} {plu(low, 'активный заказ', 'активных заказа', 'активных заказов')} — "
               "с плановой маржой ниже порога своего канала."
               if low else "Все активные заказы идут с плановой маржой не ниже порога канала.")
        exhibit("5 · Плановая экономика", ins,
                f"Плановая маржинальность активных заказов, снизу вверх. Порог шоурума "
                f"{S.margin_threshold_showroom:g} %, дилера {S.margin_threshold_dealer:g} %; "
                "красным — заказы ниже порога своего канала.")
        chart_bars_by_state(mrows, labels=230)
        st.dataframe(pd.DataFrame([{
            "Канал": D.CHANNELS[ch], "Договоров за период": v["contracts"], "С плановыми данными": v["with_data"],
            "Плановая маржинальность": pct(v["pct"]) if v["with_data"] else "нет данных",
            "Плановый МД": money(v["md"]) if v["with_data"] else "—",
            "Порог канала": f"{v['threshold']:g} %", "Ниже порога": v["below"]}
            for ch, v in k["margin_by_channel"].items()]), hide_index=True, width="stretch")
        st.caption(f"Договоры за период {k['period']} по каналам. Порог дилерского канала ниже, так как "
                   "выручка дилерского заказа не включает наценку дилера.")
        st.caption("Маржинальный доход = договорная выручка − плановая себестоимость. Это **не прибыль**: "
                   "накладные, коммерческие расходы и налоги не учтены. Фактические затраты в MVP "
                   "не ведутся. Рекламации не включаются.")

    st.subheader("Еженедельный снимок")
    st.caption("Фиксируется в конце совещания. Снимок неизменяем: последующие правки заказов его не меняют. "
               "Снимок делается по всем заказам, без учёта фильтров.")
    if st.button("Зафиксировать неделю", key="snapshot_btn", type="primary"):
        if any(sn["date"] == TODAY.isoformat() for sn in state.snapshots):  # QA D19
            st.error("Снимок за сегодня уже зафиксирован. Снимки неизменяемы; следующий — на следующем совещании.")
        else:
            full_k = D.compute_kpi(state.orders, TODAY, S)
            state.snapshots.append(D.make_snapshot(full_k, TODAY, st.session_state.user))
            persist("Снимок недели сохранён")
    snaps = state.snapshots
    if snaps:
        cols = {"Показатель": list(D.SNAPSHOT_KEYS.values())}
        for i in sorted({0, len(snaps) - 2, len(snaps) - 1} - {-1}):  # первый и два последних
            sn = snaps[i]
            title = f"№{i + 1} · {sn['date']}" + (" (неделя 1)" if i == 0 else "")
            cols[title] = [f"{m['numerator']}" + (f" из {m['denominator']}" if m["denominator"] is not None else "")
                           for m in (sn["metrics"][key] for key in D.SNAPSHOT_KEYS)]
        st.dataframe(pd.DataFrame(cols), hide_index=True, width="stretch")
        st.caption(f"Всего снимков: {len(snaps)}. Показаны первый и два последних.")
    else:
        st.caption("Снимков пока нет.")

elif page == "Реестр заказов":
    st.header("Реестр заказов")
    lead(PAGE_LEAD[page])
    filter_note()
    rank = {D.ST_OVERDUE: 0, D.ST_BLOCKED: 1, D.ST_RISK: 2, D.ST_OK: 3, D.ST_DONE: 4}
    rows = []
    for o in sorted(filtered, key=lambda x: (rank[evals[x.id].primary], x.planned_completion or date.max, x.id)):
        ev = evals[o.id]
        rows.append({"ID": o.id, "Клиент / дилер": o.client, "Канал": D.CHANNELS[o.channel],
                     "Тип": D.ORDER_TYPES[o.order_type], "Стадия": f"{o.stage}. {D.STAGES[o.stage]}",
                     "Состояние": D.STATES[ev.primary], "Признаки": flag_text(ev),
                     "Менеджер": o.manager or "—", "Отв. за стадию": o.stage_owner or "—",
                     "Следующее действие": o.next_action or "—", "Исполнитель": o.next_action_owner or "—",
                     "Срок действия": o.next_action_due, "Срок заказа": o.planned_completion,
                     "Статус обновлён": o.status_updated_at})
    df = pd.DataFrame(rows)

    def on_select():
        sel = st.session_state.registry.selection.rows
        if sel:
            open_order(df.iloc[sel[0]]["ID"])

    st.caption("Сортировка — по состоянию: просроченные сверху, завершённые внизу. "
               "Выберите строку, чтобы открыть карточку заказа.")
    date_cfg = st.column_config.DateColumn(format="DD.MM.YYYY")
    st.dataframe(df, hide_index=True, width="stretch", key="registry", on_select=on_select,
                 selection_mode="single-row", height=560,
                 column_config={c: date_cfg for c in ("Срок действия", "Срок заказа", "Статус обновлён")})

elif page == "Карточка заказа":
    ids = [o.id for o in state.orders]
    if goto_id := st.session_state.pop("goto_id", None):
        st.session_state.selected_id = goto_id
    if st.session_state.get("selected_id") not in ids:
        st.session_state.selected_id = ids[0]
    o = state.get(st.session_state.get("selected_id", ids[0]))
    ev = evals[o.id]
    fin = ev.finance
    user = st.session_state.user
    key = lambda name: f"{name}_{o.id}"  # noqa: E731 — поля сбрасываются при смене заказа

    # QA D15: версия заказа, с которой открыты формы. Если заказ изменили в другой вкладке или другой
    # пользователь, сохранение отклоняется, а поля перечитываются из файла — без «тихого» отката.
    def fingerprint(x: D.Order) -> str:
        return repr([getattr(x, f) for f in sorted(D.EDITABLE)])

    if st.session_state.pop(key("reset"), False):
        for k in [k for k in st.session_state if str(k).endswith(f"_{o.id}")]:
            del st.session_state[k]
    if key("stage") not in st.session_state or key("rev") not in st.session_state:
        st.session_state[key("rev")] = fingerprint(o)
    if err := st.session_state.pop("flash_error", None):
        st.error(err)

    st.header(f"{o.id} · {o.client}")
    lead(PAGE_LEAD[page])
    st.selectbox("Заказ", ids, key="selected_id", format_func=lambda i: f"{i} · {state.get(i).client}",
                 help="Переключение между заказами")
    st.markdown(" ".join(badge(s) for s in ev.states) + f"  Стадия {o.stage}/7: **{D.STAGES[o.stage]}**"
                + ("  · **рекламация** по заказу " + o.parent_order_id if o.order_type == "complaint" else ""))
    if o.id in SCENARIOS:
        st.caption(f"Демо-сценарий: {SCENARIOS[o.id]}")
    if text := flag_text(ev):
        st.markdown("**Признаки:** " + text)

    a, b, c = st.columns(3, border=True)
    with a:
        st.markdown("**Ответственность**")
        st.markdown(f"Канал: {D.CHANNELS[o.channel]} · {o.sales_point}  \n"
                    f"Менеджер заказа: {o.manager or ':red[не назначен]'}  \n"
                    f"Ответственный за стадию: {o.stage_owner or ':red[не назначен]'}  \n"
                    f"Следующее действие: {o.next_action or ':red[не определено]'}  \n"
                    f"Исполнитель: {o.next_action_owner or ':red[не назначен]'} · {due_text(o.next_action_due)}  \n"
                    f"Статус обновлён: {dt(o.status_updated_at)} ({(TODAY - o.status_updated_at).days} дн. назад)")
    with b:
        st.markdown("**Сроки**")
        if o.has_contract:
            verified = "сверен с договором" if o.baseline_verified else ":orange[не сверен с договором]"
            moved = f" (перенос +{ev.deadline_shift_days} дн.)" if ev.deadline_shift_days > 0 else ""
            st.markdown(f"Договор: {dt(o.contract_date)}  \n"
                        f"Первоначальный срок: {dt(o.baseline_completion)} — {verified}  \n"
                        f"Плановый срок: {dt(o.planned_completion) if o.is_closed else due_text(o.planned_completion)}"
                        f"{moved}"
                        + (f"  \nЗакрыт: {dt(o.closed_at)}" if o.is_closed else ""))
        else:
            st.markdown(f"Зарегистрирован: {dt(o.created_at)}  \nДоговор не подписан — срок заказа не оценивается.")
        durations = D.stage_durations(o, TODAY)
        st.caption("Дней по стадиям (сумма посещений): " + " · ".join(
            f"{s}: {v}" for s, v in sorted(durations.items())))
    with c:
        st.markdown("**Плановая экономика**")
        thr = S.margin_threshold(o.channel)
        st.markdown(f"Договорная выручка: {money(o.contract_price)}  \n"
                    f"Плановая себестоимость: {money(o.planned_cost)}  \n"
                    f"Плановый МД: {money(fin.plan_md)}  \n"
                    f"Плановая маржинальность: {pct(fin.plan_pct) if fin.plan_md is not None else 'нет данных'} "
                    f"(порог канала {thr:g} %)")
        if fin.note:
            st.caption(fin.note)
        st.caption("Фактические затраты в MVP не ведутся (этап 2).")

    st.subheader("Отклонения")
    if o.deviations:
        for d in reversed(o.deviations):
            tone = "green" if d.confirmed else "amber"
            with st.container(border=True, key=f"card-{tone}-{d.id}"):
                x, y = st.columns([5, 1.4], vertical_alignment="center")
                status = ":green[подтверждено " + dt(d.confirmed_at) + "]" if d.confirmed else ":orange[не подтверждено]"
                x.markdown(f"**{D.REASONS[d.reason]}** · {D.TRIGGERS[d.trigger].lower()} · {status}")
                x.caption(f"{d.comment}  \nВозникло: {d.origin_stage}. {D.STAGES[d.origin_stage]} · "
                          f"обнаружено: {d.detected_stage}. {D.STAGES[d.detected_stage]} · {dt(d.detected_at)}")
                if not d.confirmed and y.button("Подтвердить", key=f"confirm_{d.id}", width="stretch",
                                                help="Причина подтверждена на совещании"):
                    res = D.confirm_deviation(o, d.id, today=TODAY, user=user)
                    state.replace_order(res.order, res.audit)
                    persist("Отклонение подтверждено")
    else:
        st.caption("Отклонений нет.")

    def submit(changes: dict, deviation: dict | None = None, comment: str = "") -> None:
        if st.session_state.get(key("rev")) != fingerprint(o):
            st.session_state[key("reset")] = True
            st.session_state.flash_error = ("Заказ изменён в другой вкладке или другим пользователем после "
                                            "открытия формы. Ваши правки не сохранены: поля обновлены, "
                                            "проверьте их и внесите изменения заново.")
            st.rerun()
        res = D.apply_changes(o, changes, today=TODAY, user=user, deviation=deviation, comment=comment)
        if not res.ok:
            show_errors(res.errors)
        elif not res.audit:
            st.info("Изменений нет.")
        else:
            state.replace_order(res.order, res.audit)
            st.session_state[key("rev")] = fingerprint(res.order)
            persist(f"Сохранено записей журнала: {len(res.audit)}")

    st.subheader("Действия по заказу")
    if o.is_closed:
        st.info("Заказ завершён и не редактируется. Отклонения можно подтверждать; по основному заказу "
                "можно оформить рекламацию.")
    tab_names = ([] if o.is_closed else ["Шаг, стадия, срок", "Договор и экономика"]) + \
                (["Отклонение вручную"] if not o.is_closed else []) + \
                (["Рекламация"] if o.order_type == "main" else []) + \
                (["Закрытие"] if not o.is_closed else [])
    tabs = dict(zip(tab_names, st.tabs(tab_names))) if tab_names else {}
    opts = [""] + sorted(set(STAFF) | set(people))
    person = dict(format_func=lambda p: p or "— не назначен —", accept_new_options=True)

    if "Шаг, стадия, срок" in tabs:
        with tabs["Шаг, стадия, срок"], st.form(key("ops")):
            st.caption("Смена стадии требует ответственного, нового следующего действия, исполнителя и срока. "
                       "Возврат стадии, перенос срока и блокировка требуют отклонения.")
            f1, f2 = st.columns(2)
            stage = f1.selectbox("Стадия", list(D.STAGES), index=o.stage - 1, key=key("stage"),
                                 format_func=lambda s: f"{s}. {D.STAGES[s]}")
            manager = f2.selectbox("Менеджер заказа", opts, index=opts.index(o.manager) if o.manager in opts else 0,
                                   key=key("manager"), **person)
            owner = f1.selectbox("Ответственный за стадию", opts,
                                 index=opts.index(o.stage_owner) if o.stage_owner in opts else 0,
                                 key=key("owner"), **person)
            next_action = f2.text_input("Следующее действие", o.next_action, key=key("next"))
            executor = f1.selectbox("Исполнитель действия", opts,
                                    index=opts.index(o.next_action_owner) if o.next_action_owner in opts else 0,
                                    key=key("executor"), help="Если пусто, а действие задаётся сейчас, исполнителем "
                                    "станет ответственный за стадию", **person)
            next_due = f2.date_input("Срок действия", o.next_action_due, format="DD.MM.YYYY", key=key("next_due"))
            planned = None
            if o.has_contract:
                planned = f1.date_input("Плановый срок завершения", o.planned_completion, format="DD.MM.YYYY",
                                        key=key("planned"))
            blocked = f2.checkbox("Заказ заблокирован", o.is_blocked, key=key("blocked"),
                                  help="При блокировке исполнитель действия — тот, кто её снимает")
            dev = deviation_inputs(key("opsdev"), o.stage, "Отклонение (при возврате стадии, переносе срока, блокировке)")
            if st.form_submit_button("Сохранить", type="primary"):
                ch = {"stage": stage, "manager": manager or "", "stage_owner": owner or "",
                      "next_action": next_action, "next_action_owner": executor or "",
                      "next_action_due": next_due, "is_blocked": blocked}
                if o.has_contract:
                    ch["planned_completion"] = planned
                submit(ch, dev)

    if "Договор и экономика" in tabs:
        with tabs["Договор и экономика"]:
            num = dict(min_value=0.0, step=1000.0, format="%.0f")
            if not o.has_contract:
                with st.form(key("contract")):
                    st.caption("С даты договора срок заказа фиксируется как первоначальный и начинает оцениваться.")
                    g1, g2 = st.columns(2)
                    cdate = g1.date_input("Дата договора", TODAY, max_value=TODAY, format="DD.MM.YYYY",
                                          key=key("cdate"))
                    deadline = g2.date_input("Срок по договору", None, format="DD.MM.YYYY", key=key("deadline"))
                    cp = g1.number_input("Договорная выручка, ₽", value=o.contract_price, key=key("cp"), **num)
                    pc = g2.number_input("Плановая себестоимость, ₽", value=o.planned_cost, key=key("pc"), **num)
                    if st.form_submit_button("Подписан договор", type="primary"):
                        submit({"contract_date": cdate, "baseline_completion": deadline,
                                "planned_completion": deadline, "baseline_verified": deadline is not None,
                                "contract_price": cp, "planned_cost": pc})
            else:
                if not o.baseline_verified:
                    with st.form(key("verify")):
                        st.caption("Первоначальный срок не сверен с договором: заказ исключается из метрики "
                                   "срывов. Укажите срок из договора и подтвердите сверку.")
                        base = st.date_input("Срок по договору", o.baseline_completion, format="DD.MM.YYYY",
                                             key=key("base"))
                        if st.form_submit_button("Сверено с договором", type="primary"):
                            submit({"baseline_completion": base, "baseline_verified": True})
                with st.form(key("fin")):
                    st.caption("Плановые значения. Пустое поле — данных нет. Изменение сумм не обновляет "
                               "статус заказа.")
                    g1, g2 = st.columns(2)
                    cp = g1.number_input("Договорная выручка, ₽", value=o.contract_price, key=key("cp2"), **num)
                    pc = g2.number_input("Плановая себестоимость, ₽", value=o.planned_cost, key=key("pc2"), **num)
                    if st.form_submit_button("Сохранить экономику", type="primary"):
                        submit({"contract_price": cp, "planned_cost": pc})

    if "Отклонение вручную" in tabs:
        with tabs["Отклонение вручную"], st.form(key("devform")):
            st.caption("Отклонение без изменения сроков и стадии, например повторное согласование проекта.")
            dev = deviation_inputs(key("mdev"), o.stage, "Отклонение")
            if st.form_submit_button("Добавить отклонение", type="primary"):
                if not dev["reason"]:
                    st.error("Выберите причину")
                else:
                    submit({}, dev)

    if "Рекламация" in tabs:
        with tabs["Рекламация"], st.form(key("complaint")):
            st.caption("Создаёт заказ-рекламацию со ссылкой на этот заказ; отклонение записывается в этот заказ.")
            detected = D.LAST_STAGE if o.is_closed else o.stage
            dev = deviation_inputs(key("cdev"), detected, "Причина рекламации")
            r1, r2 = st.columns(2)
            cstage = r1.selectbox("Работа начинается со стадии", list(D.STAGES), index=2, key=key("cstage"),
                                  format_func=lambda s: f"{s}. {D.STAGES[s]}")
            cdeadline = r2.date_input("Срок устранения", None, format="DD.MM.YYYY", key=key("cdeadline"))
            cowner = r1.selectbox("Ответственный за стадию", opts, key=key("cowner"), **person)
            cexec = r2.selectbox("Исполнитель действия", opts, key=key("cexec"), **person)
            cnext = r1.text_input("Следующее действие", key=key("cnext"))
            cdue = r2.date_input("Срок действия", None, format="DD.MM.YYYY", key=key("cdue"))
            ccost = st.number_input("Плановая себестоимость устранения, ₽", value=None, min_value=0.0,
                                    step=1000.0, format="%.0f", key=key("ccost"))
            if st.form_submit_button("Оформить рекламацию", type="primary"):
                comp, parent, audit, errs = D.create_complaint(
                    o, {x.id for x in state.orders}, today=TODAY, user=user, deviation=dev, stage=cstage,
                    stage_owner=cowner or "", planned_completion=cdeadline, next_action=cnext,
                    next_action_owner=cexec or "", next_action_due=cdue, planned_cost=ccost)
                if errs:
                    show_errors(errs)
                else:
                    state.replace_order(parent, audit)
                    state.add_order(comp)
                    st.session_state.goto_id = comp.id  # переход применится до отрисовки виджета
                    persist(f"Оформлена рекламация {comp.id}")

    if "Закрытие" in tabs:
        with tabs["Закрытие"]:
            if o.stage != D.LAST_STAGE:
                st.info(f"Закрыть можно только заказ на стадии «{D.STAGES[D.LAST_STAGE]}». "
                        f"Сейчас: «{D.STAGES[o.stage]}».")
            else:
                with st.form(key("close")):
                    closed = st.date_input("Дата закрытия (акт подписан)", TODAY, max_value=TODAY,
                                           format="DD.MM.YYYY", key=key("closed"))
                    st.caption("Если дата позже первоначального срока, укажите отклонение.")
                    dev = deviation_inputs(key("closedev"), D.LAST_STAGE, "Отклонение (при позднем закрытии)")
                    if st.form_submit_button("Закрыть заказ", type="primary"):
                        submit({"closed_at": closed}, dev)

    st.subheader("Журнал заказа")
    log = [e for e in state.audit if e["order_id"] == o.id]
    if log:
        st.dataframe(audit_df(log, False), hide_index=True, width="stretch")
    else:
        st.caption("Изменений пока не было.")

elif page == "Журнал изменений":
    st.header("Журнал изменений")
    lead(PAGE_LEAD[page])
    if not state.audit:
        st.info("Журнал пуст.")
    else:
        only = st.multiselect("Заказ", sorted({e["order_id"] for e in state.audit}), placeholder="Все")
        entries = [e for e in state.audit if not only or e["order_id"] in only]
        st.dataframe(audit_df(entries, True), hide_index=True, width="stretch", height=520)
    st.caption("Фиксируются стадия, ответственные, исполнитель, следующее действие, сроки, блокировка, договор, "
               "плановые суммы и отклонения — со старым и новым значением. Пользователь не аутентифицирован.")

elif page == "Правила":
    st.header("Правила расчёта и ограничения")
    lead(PAGE_LEAD[page])

    st.subheader("Пороги")
    t = st.columns(4)
    for col, slug, label, value, note in (
            (t[0], "soon", "Приближается срок", f"{S.warning_days} дн.", "включительно до срока заказа"),
            (t[1], "stale", "Статус устарел", f"> {S.stale_days} дн.", "без обновления статуса"),
            (t[2], "margin", "Маржа: шоурум / дилер",
             f"{S.margin_threshold_showroom:g} / {S.margin_threshold_dealer:g} %", "дилерский порог утверждён"),
            (t[3], "period", "Период показателей", f"{S.period_days} дн.", "окно «за период»")):
        with col.container(key=f"kpi-ink-thr-{slug}"):
            st.metric(label, value)
            st.caption(note)
    st.caption("Пороги меняет администратор в конфигурации, не в интерфейсе; это демонстрационные допущения, "
               "кроме утверждённого дилерского порога.")

    st.subheader("Состояния заказа")
    st.markdown(f"""
| Состояние | Правило |
|---|---|
| **Просрочен** | у заказа **с договором** плановый срок раньше сегодняшней даты. Срок «сегодня» — ещё не просрочка |
| **Заблокирован** | установлена блокировка; она создаётся только с отклонением, действием по снятию, исполнителем и сроком |
| **Под риском** | до срока ≤ {S.warning_days} дн.; нет менеджера, ответственного за стадию или исполнителя; нет действия или срока; действие просрочено; действие запланировано после срока заказа (пока срок не нарушен); статус не обновлялся > {S.stale_days} дн. |
| **В норме** | нет признаков выше |
| **Завершён** | закрыт датой акта на стадии 7 |
""")

    st.subheader("Как считаются показатели")
    st.markdown(f"""
- Признаки не исключают друг друга; главный бейдж: Просрочен > Заблокирован > Под риском > В норме.
- «Статус обновлён» меняют стадия, ответственные, исполнитель, действие, сроки, блокировка, договор и отклонения; правка сумм — нет.
- До подписания договора срок заказа не оценивается; правила владельца и шага действуют.
- Первоначальный срок фиксируется договором. Несверенный срок можно один раз исправить при сверке; сверенный не меняется.
- Возврат стадии, перенос срока, блокировка и закрытие позже первоначального срока требуют **отклонения**: причина, стадия возникновения, описание. Пропуск стадии вперёд разрешён и фиксируется в журнале.
- Отклонения подтверждаются на совещании. Метрика «срывы с подтверждённой причиной» учитывает последнее отклонение заказа.
- «Закрыто с нарушением срока» считается за {S.period_days} дн. и за весь пилот, только по заказам со сверенным первоначальным сроком.
- Плановая маржинальность = (договорная выручка − плановая себестоимость) / договорная выручка. Это не прибыль. Рекламации в маржинальные показатели не входят.
""")

    st.subheader("Ограничения MVP")
    st.markdown("""
- Данные — в локальном файле `data/kontur_state.json`; одновременная работа нескольких пользователей не поддерживается.
- Нет авторизации: «кто вносит изменения» выбирается вручную.
- Нет импорта из таблиц и CRM; создание обычных заказов не реализовано (только рекламации по существующим).
- Нет фактических затрат, контрольных сроков стадий, графиков и выгрузки — перенесены на этап 2 (docs/01_design.md, §8.3).
- Сроки считаются в календарных днях, без учёта праздников.
""")
