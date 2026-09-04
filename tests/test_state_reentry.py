import unittest

from backend.services.learned_graph import ordered_graph_path


class StateReentryTests(unittest.TestCase):
    def test_current_state_continuation_prevents_replaying_prior_edge(self):
        transitions = [
            {"transition_id": "before", "sequence_index": 2, "from_state_id": "login", "to_state_id": "home", "step_id": "step-attendance", "postconditions": [{"kind": "selector_present", "selector": "#form"}]},
            {"transition_id": "next", "sequence_index": 3, "from_state_id": "home", "to_state_id": "form", "step_id": "step-group"},
            {"transition_id": "last", "sequence_index": 4, "from_state_id": "form", "to_state_id": "result", "step_id": "step-query"},
        ]
        self.assertEqual([item["transition_id"] for item in ordered_graph_path(transitions, "home", "result") or []], ["next", "last"])


if __name__ == "__main__":
    unittest.main()
