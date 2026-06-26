from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import reset_demo_catalog


ROOT = Path(__file__).resolve().parent.parent


class DemoResetTests(unittest.TestCase):
    def test_reset_demo_catalog_clears_actions_and_runs_but_keeps_external_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ui_map = root / "data" / "ui_map.json"
            runs = root / "data" / "runs" / "runs.json"
            external_config = root / "data" / "external_systems" / "current.json"
            external_sessions = root / "data" / "external_systems" / "sessions"
            ui_map.parent.mkdir(parents=True)
            runs.parent.mkdir(parents=True)
            external_config.parent.mkdir(parents=True)
            external_sessions.mkdir(parents=True)
            ui_map.write_text('{"acoes_conhecidas":{"Teste":{"passos_playwright":[]}}}', encoding="utf-8")
            runs.write_text('{"runs":[{"id":"run-1"}]}', encoding="utf-8")
            external_config.write_text('{"access_profile_name":"Priscila"}', encoding="utf-8")

            with patch.object(reset_demo_catalog, "ROOT", root), patch.object(
                reset_demo_catalog, "UI_MAP_PATH", ui_map
            ), patch.object(reset_demo_catalog, "RUNS_PATH", runs), patch.object(
                reset_demo_catalog, "KEEP_PATHS", (external_config, external_sessions)
            ):
                dry_run = reset_demo_catalog.reset_demo_catalog(apply=False)
                applied = reset_demo_catalog.reset_demo_catalog(apply=True)

            self.assertEqual(dry_run["ui_map_actions"], 1)
            self.assertEqual(dry_run["runs"], 1)
            self.assertEqual(applied["ui_map_actions"], 1)
            self.assertEqual(json.loads(ui_map.read_text(encoding="utf-8")), {"acoes_conhecidas": {}})
            self.assertEqual(json.loads(runs.read_text(encoding="utf-8")), {"runs": []})
            self.assertEqual(json.loads(external_config.read_text(encoding="utf-8")), {"access_profile_name": "Priscila"})


class DemoAccessProfileUiTests(unittest.TestCase):
    def test_learning_flow_no_longer_requires_access_profile_or_login_button(self) -> None:
        source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")

        self.assertIn("def render_access_profile_summary(", source)
        self.assertIn("Nome da rotina", source)
        self.assertIn("Configurações > Sistema externo", source)
        self.assertNotIn("access_profile_ready = render_access_profile_summary(session, session_id)", source)
        self.assertNotIn('"Login concluído"', source)
        self.assertNotIn('"Uso de IA na execução"', source)
        self.assertNotIn('"Timeout máximo da ação (segundos)"', source)

    def test_learning_review_warns_when_expected_inputs_have_no_fill_steps(self) -> None:
        source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Nenhum campo digitado foi capturado", source)
        self.assertIn("Salvar mesmo sem variáveis capturadas", source)

    def test_session_save_test_clear_controls_exist_in_settings(self) -> None:
        source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Abrir navegador para login", source)
        self.assertIn("Salvar sessão do navegador", source)
        self.assertIn("Testar sessão salva", source)
        self.assertIn("Limpar sessão salva", source)


if __name__ == "__main__":
    unittest.main()
