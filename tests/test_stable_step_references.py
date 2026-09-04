import unittest

from backend.services.learned_graph import (
    ensure_stable_step_ids,
    resolve_transition_step,
    stable_step_id,
    validate_compiled_action_graph,
)


def graph_fixture():
    steps = ensure_stable_step_ids([
        {"tipo": "clicar", "selector": "#a"},
        {"tipo": "preencher", "selector": "#b", "variavel": "b"},
        {"tipo": "clicar", "selector": "#c"},
        {"tipo": "extrair_texto", "selector": "#d"},
    ])
    states = [{"state_id": f"s{i}"} for i in range(5)]
    transitions = [{"transition_id": f"t{i}", "sequence_index": (i + 1) * 10, "step_id": step["step_id"], "from_state_id": f"s{i}", "to_state_id": f"s{i+1}", "action_type": step["tipo"]} for i, step in enumerate(steps)]
    return steps, states, transitions


class StableStepReferenceTests(unittest.TestCase):
    def test_non_contiguous_sequence_and_physical_reorder(self):
        steps, states, transitions = graph_fixture()
        reordered = [steps[2], steps[0], steps[3], steps[1]]
        graph = {"execution_model": "learned_graph", "passos_playwright": reordered, "learned_states": states, "learned_transitions": transitions}
        self.assertTrue(validate_compiled_action_graph(graph)["valid"])
        self.assertEqual(resolve_transition_step(transitions[1], reordered)["step_id"], steps[1]["step_id"])

    def test_dangling_step_is_blocking(self):
        steps, states, transitions = graph_fixture()
        transitions[0]["step_id"] = "step_missing"
        result = validate_compiled_action_graph({"passos_playwright": steps, "learned_states": states, "learned_transitions": transitions})
        self.assertFalse(result["valid"])
        self.assertIn("dangling_step_reference", {item["code"] for item in result["errors"]})

    def test_legacy_valid_and_invalid_index(self):
        steps, states, transitions = graph_fixture()
        legacy = dict(transitions[1]); legacy.pop("step_id"); legacy["step_index"] = 1
        self.assertEqual(resolve_transition_step(legacy, steps)["source"], "legacy_step_index")
        invalid = dict(legacy); invalid["step_index"] = 5; invalid["selector"] = "#unknown"
        self.assertIsNone(resolve_transition_step(invalid, steps))

    def test_legacy_metadata_repair(self):
        steps, _, transitions = graph_fixture()
        legacy = dict(transitions[2]); legacy.pop("step_id"); legacy["step_index"] = 99; legacy["selector"] = "#c"
        resolved = resolve_transition_step(legacy, steps)
        self.assertEqual(resolved["source"], "legacy_metadata_repair")
        self.assertEqual(resolved["step_id"], steps[2]["step_id"])


if __name__ == "__main__":
    unittest.main()
