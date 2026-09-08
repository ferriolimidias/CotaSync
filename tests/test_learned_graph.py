from __future__ import annotations

import asyncio
import unittest

from backend.services.learned_graph import (
    canonicalize_graph_metadata,
    branch_candidates,
    find_graph_path,
    graph_metadata_available,
    match_observation_to_learned_state,
    observe_browser_pages,
    ordered_graph_path,
    ordered_graph_suffix,
    transition_kind,
    evaluate_transition_satisfaction,
    fresh_run_query_start_sequence,
    validate_compiled_action_graph,
    validate_graph_reentrancy,
)
from backend.services.demo_session import _attach_learned_output_state


class FakeLocator:
    def __init__(self, visible: bool, value: str = "") -> None:
        self.visible = visible
        self.value = value

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return 1 if self.visible else 0

    async def is_visible(self) -> bool:
        return self.visible

    async def input_value(self) -> str:
        return self.value


class FakePage:
    def __init__(self, url: str, selectors: set[str], values: dict[str, str] | None = None) -> None:
        self.url = url
        self.selectors = selectors
        self.values = values or {}

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Learned page"

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(selector in self.selectors, self.values.get(selector, ""))


class LearnedGraphTests(unittest.TestCase):
    def test_new_run_starts_before_first_client_input_not_at_residual_result(self) -> None:
        steps = [
            {"step_id": "login", "tipo": "clicar", "seletor": "#login"},
            {"step_id": "open-form", "tipo": "clicar", "seletor": "#open"},
            {"step_id": "grupo", "tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"},
            {"step_id": "cota", "tipo": "preencher", "seletor": "#cota", "variavel": "cota"},
            {"step_id": "lookup", "tipo": "clicar", "seletor": "#lookup"},
        ]
        transitions = [
            {"sequence_index": 0, "from_state_id": "login", "to_state_id": "login", "step_id": "login"},
            {"sequence_index": 1, "from_state_id": "login", "to_state_id": "form", "step_id": "open-form"},
            {"sequence_index": 2, "from_state_id": "form", "to_state_id": "form", "step_id": "grupo"},
            {"sequence_index": 3, "from_state_id": "form", "to_state_id": "form", "step_id": "cota"},
            {"sequence_index": 4, "from_state_id": "form", "to_state_id": "result", "step_id": "lookup"},
        ]
        self.assertEqual(fresh_run_query_start_sequence(transitions, steps), 1)
        self.assertEqual([item["sequence_index"] for item in ordered_graph_suffix(transitions, 1, "result") or []], [1, 2, 3, 4])

    def test_new_run_boundary_is_independent_of_client_result_value(self) -> None:
        steps = [{"step_id": "lookup", "tipo": "clicar", "seletor": "#lookup"}]
        transitions = [{"sequence_index": 0, "from_state_id": "form", "to_state_id": "result", "step_id": "lookup"}]
        self.assertEqual(fresh_run_query_start_sequence(transitions, steps), None)
        # A value such as 040 is not part of graph identity or restart planning.
        self.assertIsNone(fresh_run_query_start_sequence(transitions, steps))

    def test_publication_rejects_transition_whose_step_requires_another_state(self) -> None:
        result = validate_compiled_action_graph(
            {
                "execution_model": "learned_graph",
                "robust_steps": [{"step_id": "fill", "tipo": "preencher", "before_state_id": "form"}],
                "learned_states": [{"state_id": "home"}, {"state_id": "form"}],
                "learned_transitions": [
                    {"transition_id": "t1", "sequence_index": 0, "from_state_id": "home", "to_state_id": "form", "step_id": "fill"}
                ],
            }
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "step_source_state_mismatch")

    def test_reentrancy_validator_rejects_terminal_graph_without_return_path(self) -> None:
        result = validate_graph_reentrancy(
            {
                "execution_model": "learned_graph",
                "robust_steps": [
                    {"step_id": "fill", "tipo": "preencher", "variavel": "grupo", "before_state_id": "form"},
                    {"step_id": "submit", "tipo": "clicar", "before_state_id": "form"},
                ],
                "learned_states": [{"state_id": "form"}, {"state_id": "result"}],
                "learned_transitions": [
                    {"transition_id": "fill", "sequence_index": 0, "from_state_id": "form", "to_state_id": "form", "step_id": "fill"},
                    {"transition_id": "submit", "sequence_index": 1, "from_state_id": "form", "to_state_id": "result", "step_id": "submit"},
                ],
                "output_states": [{"state_id": "result"}],
            }
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "action_not_reentrant")

    def test_visual_contract_creates_output_state_without_extraction_step(self) -> None:
        steps = [
            {
                "tipo": "preencher",
                "page_ref": "main",
                "before_state_id": "form",
                "after_state_id": "form",
                "page_signature_before": {"host": "app.test", "path": "/form", "stable_selectors": ["#input"]},
                "page_signature_after": {"host": "app.test", "path": "/form", "stable_selectors": ["#input"]},
            },
            {
                "tipo": "clicar",
                "page_ref": "main",
                "before_state_id": "form",
                "after_state_id": "old-result",
                "page_signature_before": {"host": "app.test", "path": "/form", "stable_selectors": ["#submit"]},
                "page_signature_after": {"host": "app.test", "path": "/result", "stable_selectors": ["#submit"]},
            },
        ]
        updated, output = _attach_learned_output_state(
            steps,
            {
                "target_name": "Número de parcelas",
                "selector_data": {"primary": "#resultado"},
                "read_mode": "text",
                "normalization": {"type": "digits_only"},
            },
            "Número de parcelas",
        )
        self.assertEqual(output["label"], "Número de parcelas")
        self.assertEqual(output["locator"], "#resultado")
        self.assertEqual(output["state_id"], updated[-1]["after_state_id"])
        self.assertEqual(updated[-1]["page_signature_after"]["output_selector"], "#resultado")

    def test_same_state_sequence_is_not_classified_as_branch(self) -> None:
        transitions = [
            {"from_state_id": "s1", "to_state_id": "s1", "sequence_index": 0, "action_type": "preencher"},
            {"from_state_id": "s1", "to_state_id": "s1", "sequence_index": 1, "action_type": "preencher"},
        ]
        self.assertEqual([transition_kind(item) for item in transitions], ["sequence", "sequence"])
        self.assertEqual(branch_candidates(transitions, "s1"), [])

    def test_explicit_branch_is_available_without_inventing_business_rules(self) -> None:
        transitions = [
            {"from_state_id": "s1", "to_state_id": "s2", "transition_kind": "branch", "branch_id": "choice"},
            {"from_state_id": "s1", "to_state_id": "s3", "transition_kind": "branch", "branch_id": "choice"},
        ]
        self.assertEqual(len(branch_candidates(transitions, "s1")), 2)

    def test_same_state_click_uses_postcondition_during_reentry(self) -> None:
        transition = {
            "from_state_id": "s1",
            "to_state_id": "s1",
            "postconditions": [{"kind": "selector_present", "selector": "#form"}],
        }
        before = FakePage("https://app.test/main", {"#button"})
        after = FakePage("https://app.test/main", {"#button", "#form"})
        self.assertEqual(asyncio.run(evaluate_transition_satisfaction(before, transition)), "not_satisfied")
        self.assertEqual(asyncio.run(evaluate_transition_satisfaction(after, transition)), "satisfied")

    def test_ordered_suffix_starts_at_unsatisfied_same_state_transition(self) -> None:
        transitions = [
            {"sequence_index": 0, "from_state_id": "s0", "to_state_id": "s1"},
            {"sequence_index": 1, "from_state_id": "s1", "to_state_id": "s1"},
            {"sequence_index": 2, "from_state_id": "s1", "to_state_id": "s2"},
        ]
        suffix = ordered_graph_suffix(transitions, 1, "s2")
        self.assertEqual([item["sequence_index"] for item in suffix or []], [1, 2])

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

    def test_ordered_path_keeps_same_state_transitions(self) -> None:
        transitions = [
            {"sequence_index": 0, "from_state_id": "s1", "to_state_id": "s1", "step_index": 0},
            {"sequence_index": 1, "from_state_id": "s1", "to_state_id": "s1", "step_index": 1},
            {"sequence_index": 2, "from_state_id": "s1", "to_state_id": "s2", "step_index": 2},
        ]
        path = ordered_graph_path(transitions, "s1", "s2")
        self.assertEqual([item["step_index"] for item in path or []], [0, 1, 2])

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
