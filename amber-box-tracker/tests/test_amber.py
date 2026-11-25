"""Amber tools, offline provider and LLM tool loop (fake clients). No network."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.amber import tools
from app.amber.anthropic_provider import AnthropicProvider
from app.amber.offline_provider import OfflineAmberProvider
from app.amber.provider import get_provider
from app.amber.tools import AlertView, CartonView, DeliveryView


def _c(code: str, po: str, part: str, name: str, shelf: str, level: int,
       seen: tuple[int, str] | None = None) -> CartonView:
    return CartonView(f"KYC1:{code}", po, part, name, "received", "DEL-2211", level, shelf,
                      seen[0] if seen else None, seen[1] if seen else None)


class FakeStore:
    def __init__(self) -> None:
        self.cartons = [
            _c("BV2401", "PO-1077", "BV-200-SS", "2in ball valve", "L2-B2", 2, (2, "L2-B2")),
            _c("BV2402", "PO-1077", "BV-200-SS", "2in ball valve", "L2-B2", 2),
            _c("BF1201", "PO-1077", "BF-300-LUG", "3in butterfly valve", "L2-B1", 2),
            _c("YS0601", "PO-1077", "YS-250", "Y strainer", "L2-B1", 2),
            _c("CH0201", "PO-1042", "CVHF-0500", "chiller parts kit CH-2", "L3-A1", 3),
        ]
        self.located: list[str] = []
        self.damaged: list[tuple[str, str]] = []
        self.resolved: list[tuple[int, str]] = []

    def list_cartons(self) -> list[CartonView]:
        return self.cartons

    def get_carton(self, code: str) -> CartonView | None:
        return next((c for c in self.cartons if c.label_code == code), None)

    def get_delivery(self, delivery_id: str) -> DeliveryView | None:
        if delivery_id != "DEL-2211":
            return None
        return DeliveryView(delivery_id, tuple(c.label_code for c in self.cartons[:4]),
                            ("KYC1:BV2401", "KYC1:BF1201"))

    def open_alerts(self) -> list[AlertView]:
        return [AlertView(1, "wrong_floor", "Box KYC1:CH0201 is on Floor 2.", "KYC1:CH0201")]

    def locate(self, code: str) -> dict[str, Any]:
        self.located.append(code)
        return {"queued": True, "code": code}

    def resolve_alert(self, alert_id: int, note: str) -> bool:
        self.resolved.append((alert_id, note))
        return alert_id == 1

    def create_damage(self, code: str, note: str) -> int:
        self.damaged.append((code, note))
        return 7


@pytest.fixture()
def store() -> FakeStore:
    return FakeStore()


def test_fuzzy_find_tolerates_typos(store: FakeStore) -> None:
    out = tools.find_carton(store, "ball valv")
    assert {m["label_code"] for m in out["matches"]} == {"KYC1:BV2401", "KYC1:BV2402"}
    assert tools.find_carton(store, "bal valve")["matches"]
    assert tools.find_carton(store, "zzzzqq")["matches"] == []


def test_find_by_part_and_po_case_insensitive(store: FakeStore) -> None:
    assert tools.find_carton(store, "ys-250")["matches"][0]["label_code"] == "KYC1:YS0601"
    assert tools.find_carton(store, "po-1042")["matches"][0]["label_code"] == "KYC1:CH0201"


def test_auto_locate_only_when_asked(store: FakeStore) -> None:
    tools.find_carton(store, "strainer")
    assert store.located == []
    tools.find_carton(store, "strainer", auto_locate=True)
    assert store.located == ["KYC1:YS0601"]


def test_where_does_this_go_accepts_bare_code(store: FakeStore) -> None:
    assert tools.where_does_this_go(store, "bv2401")["destination"] == "Floor 2, shelf L2-B2"
    assert tools.where_does_this_go(store, "NOPE00")["found"] is False


def test_delivery_status_lists_missing(store: FakeStore) -> None:
    out = tools.delivery_status(store, "del-2211")
    assert (out["expected"], out["seen"]) == (4, 2)
    assert out["missing_codes"] == ["KYC1:BV2402", "KYC1:YS0601"]
    assert tools.delivery_status(store, "DEL-9")["found"] is False


def test_report_damage_is_two_step(store: FakeStore) -> None:
    first = tools.report_damage(store, "BV2401", "dented")
    assert first["needs_confirmation"] is True
    assert store.damaged == []
    done = tools.report_damage(store, "BV2401", "dented", confirm=True)
    assert done["recorded"] is True
    assert store.damaged == [("KYC1:BV2401", "dented")]


def test_offline_intents(store: FakeStore) -> None:
    p = OfflineAmberProvider(store)
    assert "Floor 2, shelf L2-B2" in p.chat("where does KYC1:BV2401 go?").reply
    assert "2 of 4 cartons seen" in p.chat("status of DEL-2211").reply
    assert "1 open" in p.chat("any open alerts?").reply
    r = p.chat("where is the ball valve")
    assert "L2-B2" in r.reply and r.tool_calls[0]["name"] == "find_carton"
    assert store.located == []
    p.chat("light up the Y strainer")
    assert store.located == ["KYC1:YS0601"]


def test_offline_damage_confirmation_flow(store: FakeStore) -> None:
    p = OfflineAmberProvider(store)
    r = p.chat("KYC1:BV2401 is damaged: crushed corner")
    assert r.needs_confirmation and store.damaged == []
    r2 = p.chat("KYC1:BV2401 is damaged: crushed corner", confirm=True)
    assert not r2.needs_confirmation
    assert store.damaged == [("KYC1:BV2401", "crushed corner")]


def test_offline_never_invents_locations(store: FakeStore) -> None:
    p = OfflineAmberProvider(store)
    assert "nothing matching" in p.chat("find unobtainium").reply
    assert "can't find" in p.chat("where does ZZZZZZ go").reply
    assert p.chat("tell me a joke").tool_calls == []


def test_get_provider_falls_back_offline(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert get_provider(store).name == "offline"


class FakeAnthropic:
    """First reply asks for a tool, second reply is text."""

    def __init__(self, tool_input: dict[str, Any], tool_name: str = "report_damage") -> None:
        self.n = 0
        self.tool = (tool_name, tool_input)
        self.messages = self

    def create(self, **_: Any) -> Any:
        self.n += 1
        if self.n == 1:
            block = SimpleNamespace(type="tool_use", id="t1", name=self.tool[0], input=self.tool[1])
            return SimpleNamespace(stop_reason="tool_use", content=[block])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text="Done.")])


def test_anthropic_loop_cannot_self_confirm(store: FakeStore) -> None:
    client = FakeAnthropic({"carton_code": "BV2401", "note": "x", "confirm": True})
    r = AnthropicProvider(store, client=client).chat("BV2401 is damaged")
    assert r.needs_confirmation and store.damaged == []
    assert r.tool_calls[0]["name"] == "report_damage"


def test_anthropic_loop_records_after_user_confirm(store: FakeStore) -> None:
    client = FakeAnthropic({"carton_code": "BV2401", "note": "x"})
    r = AnthropicProvider(store, client=client).chat("BV2401 is damaged", confirm=True)
    assert r.reply == "Done." and store.damaged == [("KYC1:BV2401", "x")]


def test_unknown_tool_returns_error(store: FakeStore) -> None:
    client = FakeAnthropic({}, tool_name="drop_tables")
    r = AnthropicProvider(store, client=client).chat("hi")
    assert "error" in r.tool_calls[0]["result"]


def test_light_it_up_uses_previous_find(store: FakeStore) -> None:
    p = OfflineAmberProvider(store)
    assert p.chat("light it up").tool_calls == []
    p.chat("where is the Y strainer")
    assert store.located == []
    p.chat("Light it up")
    assert store.located == ["KYC1:YS0601"]


def test_acceptance_phrases(store: FakeStore) -> None:
    p = OfflineAmberProvider(store)
    assert "KYC1:BV2401" in p.chat("where is BV2401").reply
    assert "cartons seen" in p.chat("status of DEL-2211").reply


def test_exact_label_code_returns_only_that_carton(store: FakeStore) -> None:
    out = tools.find_carton(store, "bv2401")
    assert [m["label_code"] for m in out["matches"]] == ["KYC1:BV2401"]
    assert out["matches"][0]["score"] == 1.0
