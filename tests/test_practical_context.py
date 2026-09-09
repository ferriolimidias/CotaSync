import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.teaching_context import TeachingContextError, resolve_teaching_context


class TeachingContextTests(unittest.TestCase):
    def setUp(self):
        self.system = {"id": "system-a", "run_start_strategy": "external_entry_each_run", "entry_url": "https://example.test/entry"}
        self.profiles = [{"id": "a", "display_name": "Access A", "active": True}]

    def resolve(self, profiles=None, rows=(), sheet=None, **kwargs):
        db = MagicMock()
        db.scalars.return_value = rows
        db.get.return_value = sheet
        with patch("backend.services.teaching_context.load_current_external_system", return_value=self.system), patch("backend.services.teaching_context.list_access_profiles", return_value=self.profiles if profiles is None else profiles), patch("backend.services.teaching_context.SessionLocal") as factory:
            factory.return_value.__enter__.return_value = db
            return resolve_teaching_context(**kwargs)

    def test_unique_access_is_resolved_without_session_creation(self):
        context = self.resolve()
        self.assertEqual(context["required_access_profile_id"], "a")
        self.assertEqual(context["run_start_strategy"], "external_entry_each_run")

    def test_multiple_accesses_require_choice(self):
        with self.assertRaises(TeachingContextError):
            self.resolve(profiles=self.profiles + [{"id": "b", "display_name": "B", "active": True}])

    def test_sheet_resolves_list_and_access(self):
        context = self.resolve(spreadsheet_id="sheet", sheet=SimpleNamespace(source_type="system_spreadsheet", configuration={"default_list_id": "list-a"}), rows=[SimpleNamespace(access_profile_id="a")])
        self.assertEqual(context["allowed_list_ids"], ["list-a"])
        self.assertEqual(context["required_access_profile_id"], "a")

    def test_list_conflict_is_rejected(self):
        with self.assertRaisesRegex(TeachingContextError, "outro acesso"):
            self.resolve(profile_id="b", list_ids=["list-a"], rows=[SimpleNamespace(access_profile_id="a")])

    def test_unbound_list_is_rejected(self):
        with self.assertRaises(TeachingContextError):
            self.resolve(list_ids=["list-a"], rows=[SimpleNamespace(access_profile_id=None)])


class ResumeTeachingTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_resume_preserves_steps_and_multiple_outputs(self):
        from backend.services.demo_session import DemoSessionManager
        manager = DemoSessionManager()
        session = SimpleNamespace(id="draft", status="interrupted", recording=False, publication_status="not_attempted", access_profile_id="a", steps=[{"variavel": "versao", "valor": "00"}], learning_events=[{"event_type": "fill"}], outputs=[{"id": "one"}, {"id": "two"}, {"id": "three"}])
        with patch.object(manager, "ensure_session", AsyncMock(return_value=session)), patch.object(manager, "_install_recorder_for_session", AsyncMock()), patch.object(manager, "status", AsyncMock(return_value={})), patch("backend.services.demo_session.persist_learning_session") as persist:
            await manager.resume_recording("draft")
        self.assertTrue(session.recording)
        self.assertEqual(session.steps, [{"variavel": "versao", "valor": "00"}])
        self.assertEqual(len(session.outputs), 3)
        persist.assert_called_once_with(session)


class NewListContextTests(unittest.TestCase):
    def create(self, profiles, access=None):
        from backend.services.client_lists import create_client_list
        db = MagicMock()
        db.scalar.side_effect = [SimpleNamespace(id="system-a", config={"run_start_strategy": "external_entry_each_run"}), None]
        db.scalars.return_value = profiles
        with patch("backend.services.client_lists.SessionLocal") as factory, patch("backend.services.access_profiles.validate_profile_binding"):
            factory.begin.return_value.__enter__.return_value = db
            return create_client_list("New list", access_profile_id=access)

    def test_unique_profile_is_assigned_before_insert(self):
        self.assertEqual(self.create([SimpleNamespace(id="a")])["access_profile_id"], "a")

    def test_multiple_profiles_require_explicit_choice(self):
        from backend.services.client_lists import ClientListError
        with self.assertRaises(ClientListError):
            self.create([SimpleNamespace(id="a"), SimpleNamespace(id="b")])
        self.assertEqual(self.create([SimpleNamespace(id="a"), SimpleNamespace(id="b")], "b")["access_profile_id"], "b")

    def test_no_profile_never_creates_unbound_list(self):
        from backend.services.client_lists import ClientListError
        with self.assertRaises(ClientListError):
            self.create([])
