import inspect
import unittest
from unittest.mock import MagicMock, patch

from app.config import Settings, get_settings
from app.dependencies import get_project_service, get_repository
from app.repositories import InMemoryProjectRepository


class DependencyFactoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_repository.cache_clear()
        get_settings.cache_clear()

    def test_dependency_signatures_remain_explicit(self) -> None:
        self.assertEqual(
            str(inspect.signature(get_repository)),
            "() -> app.repositories.base.ProjectRepository",
        )
        self.assertIn("Depends(get_repository)", str(inspect.signature(get_project_service)))

    @patch("app.dependencies.firestore.Client")
    def test_memory_mode_does_not_construct_firestore_client(self, client) -> None:
        get_repository.cache_clear()
        with patch("app.dependencies.get_settings") as settings:
            settings.return_value = Settings(
                app_env="testing",
                repository_backend="memory",
                demo_mode=False,
                demo_max_projects=1,
            )
            repository = get_repository()

        self.assertIsInstance(repository, InMemoryProjectRepository)
        self.assertIsNone(repository._max_active_projects)
        client.assert_not_called()

    @patch("app.dependencies.FirestoreProjectRepository")
    @patch("app.dependencies.firestore.Client")
    def test_firestore_mode_passes_options_and_reuses_repository(
        self,
        client,
        repository_class,
    ) -> None:
        get_repository.cache_clear()
        repository = MagicMock()
        repository_class.return_value = repository
        client.return_value = MagicMock()
        with patch("app.dependencies.get_settings") as settings:
            settings.return_value = Settings(
                repository_backend="firestore",
                firestore_project_id="portal-project",
                firestore_database="portal-db",
                demo_mode=True,
                demo_max_projects=3,
            )
            first = get_repository()
            second = get_repository()

        self.assertIs(first, repository)
        self.assertIs(second, repository)
        client.assert_called_once_with(
            project="portal-project",
            database="portal-db",
        )
        repository_class.assert_called_once_with(
            client=client.return_value,
            max_active_projects=3,
        )


if __name__ == "__main__":
    unittest.main()
