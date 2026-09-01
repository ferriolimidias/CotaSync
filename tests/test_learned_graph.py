from __future__ import annotations

import asyncio
import unittest

from backend.services.learned_graph import (
    canonicalize_graph_metadata,
    find_graph_path,
    graph_metadata_available,
    match_observation_to_learned_state,
    observe_browser_pages,
)


class FakeLocator:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return 1 if self.visible else 0

    async def is_visible(self) -> bool:
        return self.visible


class FakePage:
    def __init__(self, url: str, selectors: set[str]) -> None:
        self.url = url
        self.selectors = selectors

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Learned page"

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(selector in self.selectors)


class LearnedGraphTests(unittest.TestCase):
    def test_canonicalization_reuses_same_structural_state_and_keeps_self_loop(self) -> None:
        action = {
            "execution_model": "learned_graph",
            "learned_states": [
                {"state_id": "before", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "stable_selectors": ["#grupo"]}},
                {"state_id": "after", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "stable_selectors": ["#grupo"]}},
                {"state_id": "result", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "output_selector": "#resultado"}},
            ],
            "learned_transitions": [
                {"from_state_id": "before", "to_state_id": "after", "step_index": 0, "action_type": "preencher"},
                {"from_state_id": "after", "to_state_id": "result", "step_index": 1, "action_type": "clicar"},
            ],
            "output_states": [{"state_id": "result", "label": "Resultado"}],
        }
        canonical = canonicalize_graph_metadata(action)
        self.assertEqual(len(canonical["learned_states"]), 2)
        self.assertEqual(canonical["learned_transitions"][0]["from_state_id"], canonical["learned_transitions"][0]["to_state_id"])
        self.assertEqual(canonical["output_states"][0]["state_id"], "result")

    def test_canonicalization_ignores_legacy_step_selector_but_keeps_markers(self) -> None:
        action = {
            "execution_model": "learned_graph",
            "learned_states": [
                {"state_id": "grupo", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "title": "Form", "selector": "#grupo"}},
                {"state_id": "cota", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "title": "Form", "selector": "#cota"}},
            ],
            "learned_transitions": [
                {"from_state_id": "grupo", "to_state_id": "cota", "step_index": 0, "action_type": "preencher"},
            ],
        }
        canonical = canonicalize_graph_metadata(action)
        self.assertEqual(len(canonical["learned_states"]), 1)
        self.assertEqual(canonical["learned_states"][0]["signature"]["legacy_markers"], ["#grupo", "#cota"])

    def test_same_page_observation_matches_one_canonical_state(self) -> None:
        action = {
            "execution_model": "learned_graph",
            "learned_states": [
                {"state_id": "main-before", "page_ref": "main", "signature": {"host": "app.test", "path": "/main", "title": "App", "selector": "#atendimento"}},
                {"state_id": "main-after", "page_ref": "main", "signature": {"host": "app.test", "path": "/main", "title": "App", "selector": "#grupo"}},
            ],
            "learned_transitions": [
                {"from_state_id": "main-before", "to_state_id": "main-after", "step_index": 0, "action_type": "preencher"},
            ],
        }
        canonical = canonicalize_graph_metadata(action)
        match = match_observation_to_learned_state(
            [{"host": "app.test", "path": "/main", "title": "App", "visible_selectors": ["#atendimento"]}],
            canonical["learned_states"],
        )
        self.assertEqual(match["status"], "matched")
        self.assertEqual(match["state_id"], "main-before")

    def test_graph_metadata_and_bfs_path(self) -> None:
        action = {
            "execution_model": "learned_graph",
            "learned_states": [{"state_id": "s1"}, {"state_id": "s2"}],
            "learned_transitions": [{"from_state_id": "s1", "to_state_id": "s2", "step_index": 3}],
        }
        self.assertTrue(graph_metadata_available(action))
        path = find_graph_path(action["learned_transitions"], "s1", "s2")
        self.assertEqual([item["step_index"] for item in path or []], [3])

    def test_equal_state_matches_are_ambiguous(self) -> None:
        states = [
            {"state_id": "s1", "signature": {"host": "app.test", "path": "/home"}},
            {"state_id": "s2", "signature": {"host": "app.test", "path": "/home"}},
        ]
        result = match_observation_to_learned_state(
            [{"host": "app.test", "path": "/home", "title": "", "visible_selectors": []}],
            states,
        )
        self.assertEqual(result["status"], "ambiguous")

    def test_observes_all_open_pages(self) -> None:
        main = FakePage("https://main.test/home", {"#main"})
        popup = FakePage("https://popup.test/form", {"#form"})
        context = type("Context", (), {"pages": [main, popup]})()
        states = [{"state_id": "s1", "page_ref": "page_2", "signature": {"selector": "#form"}}]
        result = asyncio.run(observe_browser_pages(context, states))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["visible_selectors"], ["#form"])
