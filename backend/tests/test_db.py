import unittest

from pydantic import ValidationError

from app.config import Settings


class DatabaseStartupSettingsTests(unittest.TestCase):
    def test_database_startup_retry_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(settings.db_startup_max_attempts, 60)
        self.assertEqual(settings.db_startup_retry_delay_seconds, 5.0)

    def test_database_startup_retry_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, db_startup_max_attempts=0)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, db_startup_retry_delay_seconds=-0.1)

    def test_database_startup_retry_accepts_zero_delay(self) -> None:
        settings = Settings(
            _env_file=None,
            db_startup_max_attempts=1,
            db_startup_retry_delay_seconds=0,
        )

        self.assertEqual(settings.db_startup_max_attempts, 1)
        self.assertEqual(settings.db_startup_retry_delay_seconds, 0)


if __name__ == "__main__":
    unittest.main()
