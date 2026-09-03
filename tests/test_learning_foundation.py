from __future__ import annotations

import unittest

from backend.services.learning_ai import (
    LearningAIObserver,
    compile_validated_learning_metadata,
    validate_postcondition_candidate,
    validate_selector_candidate,
)
from backend.services.learning_outputs import normalize_outputs
from backend.services.learning_trace import build_raw_learning_trace, sanitize_trace


class LearningFoundationTests(unittest.TestCase):
    def test_legacy_contract_is_an_output_list(self):
        outputs = normalize_outputs({"extraction_review": {"target_name": "Parcelas", "example_value": "034"}})
        self.assertEqual(outputs[0]["output_id"], "output_1")
        self.assertEqual(outputs[0]["type"], "data")

    def test_actions_without_output_are_valid(self):
        self.assertEqual(normalize_outputs({}), [])

    def test_selector_candidate_must_resolve_same_node(self):
        candidate = {"selector": "#stable"}
        self.assertTrue(validate_selector_candidate(candidate=candidate, captured_node_id="node-1", resolved_node_ids=["node-1"]))
        self.assertFalse(validate_selector_candidate(candidate=candidate, captured_node_id="node-1", resolved_node_ids=["node-2"]))
        self.assertFalse(validate_selector_candidate(candidate=candidate, captured_node_id="node-1", resolved_node_ids=["node-1", "node-2"]))

    def test_postcondition_candidate_requires_before_after_evidence(self):
        candidate = {"kind": "selector_present", "selector": "#result"}
        self.assertTrue(validate_postcondition_candidate(candidate=candidate, before_selectors=set(), after_selectors={"#result"}))
        self.assertFalse(validate_postcondition_candidate(candidate=candidate, before_selectors={"#result"}, after_selectors={"#result"}))

    def test_trace_redacts_secrets_and_contains_diff(self):
        events = [{"password": "secret", "page_signature_before": {"path": "/a"}, "page_signature_after": {"path": "/b"}}]
        trace = build_raw_learning_trace(events)
        self.assertNotIn("secret", str(trace))
        self.assertEqual(trace[0]["before_after_diff"]["path"]["after"], "/b")
        self.assertNotIn("token", str(sanitize_trace({"token": "secret"})))

    def test_ai_disabled_does_not_block_learning(self):
        self.assertFalse(LearningAIObserver().analyze([])["enabled"])

    def test_compiler_accepts_only_validated_suggestions(self):
        compiled, report = compile_validated_learning_metadata(
            {"selector": "#original", "before_selectors": [], "after_selectors": ["#next"]},
            selector_candidates=[{"selector": "#same-node", "validated": True}, {"selector": "#other", "validated": False}],
            postcondition_candidates=[{"kind": "selector_present", "selector": "#next"}],
        )
        self.assertEqual(compiled["fallback_selectors"], ["#same-node"])
        self.assertEqual(report.validated_postconditions[0]["selector"], "#next")


if __name__ == "__main__":
    unittest.main()
