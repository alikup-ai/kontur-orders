"""Хранение состояния в локальном JSON-файле (NFR-04).

Ограничение: однопользовательский режим. При одновременной работе двух
пользователей сохраняется версия того, кто записал последним.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import demo_data
from .domain import Order, Settings

SCHEMA_VERSION = 2
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "kontur_state.json"


def data_path() -> Path:
    return Path(os.environ.get("KONTUR_DATA", DEFAULT_PATH))


class State:
    def __init__(self, orders: list[Order], audit: list[dict], settings: Settings,
                 generated_for: str, snapshots: list[dict] | None = None):
        self.orders = orders
        self.audit = audit
        self.settings = settings
        self.generated_for = generated_for
        self.snapshots = snapshots or []

    def get(self, order_id: str) -> Order | None:
        return next((o for o in self.orders if o.id == order_id), None)

    def replace_order(self, order: Order, audit: list[dict]) -> None:
        self.orders = [order if o.id == order.id else o for o in self.orders]
        self.audit.extend(audit)

    def add_order(self, order: Order) -> None:
        if self.get(order.id):
            raise ValueError(f"Заказ {order.id} уже существует")
        self.orders.append(order)

    def to_dict(self) -> dict:
        return {"version": SCHEMA_VERSION, "synthetic": True, "generated_for": self.generated_for,
                "settings": asdict(self.settings), "orders": [o.to_dict() for o in self.orders],
                "audit": self.audit, "snapshots": self.snapshots}

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        if d.get("version") != SCHEMA_VERSION:
            raise ValueError(f"версия схемы {d.get('version')}, ожидается {SCHEMA_VERSION}")
        orders = [Order.from_dict(x) for x in d["orders"]]
        ids = [o.id for o in orders]
        if len(ids) != len(set(ids)):
            raise ValueError("Дубликаты ID заказов в файле данных")
        return cls(orders, list(d.get("audit", [])), Settings.from_dict(d.get("settings")),
                   d.get("generated_for", ""), list(d.get("snapshots", [])))


def demo_state(today: date) -> State:
    return State(demo_data.build(today), demo_data.seed_audit(today), Settings(), today.isoformat())


def save(state: State, path: Path | None = None) -> None:
    path = path or data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".kontur_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)  # атомарная замена: файл не останется наполовину записанным
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load(today: date, path: Path | None = None) -> tuple[State, str | None]:
    """Загружает состояние; при отсутствии файла создаёт демо-набор.

    Повреждённый файл или файл старой схемы не перезаписывается молча:
    он переименовывается в *.broken.json, пользователь получает предупреждение."""
    path = path or data_path()
    if not path.exists():
        st = demo_state(today)
        save(st, path)
        return st, None
    try:
        return State.from_dict(json.loads(path.read_text(encoding="utf-8"))), None
    except (ValueError, KeyError, TypeError) as exc:
        broken = path.with_suffix(".broken.json")
        os.replace(path, broken)
        st = demo_state(today)
        save(st, path)
        return st, (f"Файл данных не прочитан ({exc}); сохранён как {broken.name}, "
                    "загружен демонстрационный набор.")


def reset(today: date, path: Path | None = None) -> State:
    st = demo_state(today)
    save(st, path)
    return st
