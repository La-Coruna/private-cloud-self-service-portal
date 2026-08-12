import unittest
from unittest.mock import MagicMock, call, patch

from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app import db as db_module
from app.config import Settings


def operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionRefusedError("unavailable"))


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


class WaitForDatabaseTests(unittest.TestCase):
    @patch("time.sleep")
    @patch("app.db.engine.connect")
    def test_returns_immediately_when_database_is_ready(
        self,
        connect: MagicMock,
        sleep: MagicMock,
    ) -> None:
        connection = MagicMock()
        connect.return_value.__enter__.return_value = connection

        db_module.wait_for_database(max_attempts=3, retry_delay_seconds=5)

        connect.assert_called_once_with()
        connection.execute.assert_called_once()
        sleep.assert_not_called()

    @patch("time.sleep")
    @patch("app.db.engine.connect")
    def test_retries_operational_error_then_succeeds(
        self,
        connect: MagicMock,
        sleep: MagicMock,
    ) -> None:
        success = MagicMock()
        success.__enter__.return_value = MagicMock()
        connect.side_effect = [operational_error(), operational_error(), success]

        with self.assertLogs("app.db", level="WARNING") as captured_logs:
            db_module.wait_for_database(max_attempts=3, retry_delay_seconds=5)

        self.assertEqual(connect.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(5), call(5)])
        log_output = " ".join(captured_logs.output)
        self.assertIn("attempt 1/3", log_output)
        self.assertIn("attempt 2/3", log_output)
        self.assertNotIn("ConnectionRefusedError", log_output)
        self.assertNotIn("SELECT 1", log_output)
        self.assertNotIn("mysql", log_output.lower())
        self.assertNotIn("portal_pass", log_output)

    @patch("time.sleep")
    @patch("app.db.engine.connect")
    def test_raises_final_operational_error_without_final_sleep(
        self,
        connect: MagicMock,
        sleep: MagicMock,
    ) -> None:
        failures = [operational_error(), operational_error(), operational_error()]
        connect.side_effect = failures

        with self.assertRaises(OperationalError) as raised:
            db_module.wait_for_database(max_attempts=3, retry_delay_seconds=5)

        self.assertIs(raised.exception, failures[-1])
        self.assertEqual(sleep.call_args_list, [call(5), call(5)])

    @patch("time.sleep")
    @patch("app.db.engine.connect")
    def test_does_not_retry_unexpected_exception(
        self,
        connect: MagicMock,
        sleep: MagicMock,
    ) -> None:
        connect.side_effect = RuntimeError("programming defect")

        with self.assertRaisesRegex(RuntimeError, "programming defect"):
            db_module.wait_for_database(max_attempts=3, retry_delay_seconds=5)

        connect.assert_called_once_with()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
