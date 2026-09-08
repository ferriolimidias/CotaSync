import unittest

from backend.services.learned_graph import match_observation_to_learned_state, ordered_graph_path


class StateReentryTests(unittest.TestCase):
    state = {"state_id": "form", "page_ref": "main", "signature": {"host": "app.test", "path": "/form", "title": "Form", "stable_selectors": ["#submit"]}}

    def test_same_observation_matches_for_planner_and_executor(self):
        observation = {"host": "app.test", "path": "/form", "title": "Form", "visible_selectors": ["#submit"], "client_values": {"grupo": "935"}}
        planner = match_observation_to_learned_state([observation], [self.state])
        executor = match_observation_to_learned_state([observation], [self.state])
        self.assertEqual((planner["status"], planner["state_id"]), (executor["status"], executor["state_id"]))

    def test_dynamic_text_and_client_data_do_not_change_structural_match(self):
        for value in ("123", "456"):
            result = match_observation_to_learned_state([{"host": "app.test", "path": "/form", "title": "Form", "visible_selectors": ["#submit"], "text": value, "client_values": {"grupo": value}}], [self.state])
            self.assertEqual(result["status"], "matched")

    def test_required_selector_missing_and_different_page_do_not_match(self):
        missing = match_observation_to_learned_state([{"host": "app.test", "path": "/form", "title": "Form", "visible_selectors": []}], [self.state])
        other_page = match_observation_to_learned_state([{"host": "login.microsoftonline.com", "path": "/", "title": "Login", "visible_selectors": ["#submit"]}], [self.state])
        self.assertEqual(missing["status"], "unknown")
        self.assertEqual(other_page["status"], "unknown")

    def test_same_host_path_drift_uses_structural_evidence(self):
        state = {
            "state_id": "result",
            "signature": {
                "host": "app.test",
                "path": "/historical/result",
                "stable_selectors": ["#menu", "#output"],
                "output_selector": "#output",
            },
        }
        result = match_observation_to_learned_state(
            [{"host": "app.test", "path": "/current/result", "title": "App", "visible_selectors": ["#menu", "#output"]}],
            [state],
        )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["state_id"], "result")

    def test_path_drift_does_not_override_a_stronger_structural_candidate(self):
        states = [
            {"state_id": "screen", "signature": {"host": "app.test", "path": "/home", "stable_selectors": ["#menu", "#action"]}},
            {"state_id": "result", "signature": {"host": "app.test", "path": "/result", "stable_selectors": ["#menu", "#action", "#output"], "output_selector": "#output"}},
        ]
        result = match_observation_to_learned_state(
            [{"host": "app.test", "path": "/legacy/result", "title": "App", "visible_selectors": ["#menu", "#action", "#output"]}],
            states,
        )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["state_id"], "result")
    def test_current_state_continuation_prevents_replaying_prior_edge(self):
        transitions = [
            {"transition_id": "before", "sequence_index": 2, "from_state_id": "login", "to_state_id": "home", "step_id": "step-attendance", "postconditions": [{"kind": "selector_present", "selector": "#form"}]},
            {"transition_id": "next", "sequence_index": 3, "from_state_id": "home", "to_state_id": "form", "step_id": "step-group"},
            {"transition_id": "last", "sequence_index": 4, "from_state_id": "form", "to_state_id": "result", "step_id": "step-query"},
        ]
        self.assertEqual([item["transition_id"] for item in ordered_graph_path(transitions, "home", "result") or []], ["next", "last"])


if __name__ == "__main__":
    unittest.main()
