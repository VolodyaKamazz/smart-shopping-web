import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from config.settings import DEV_SECRET_KEY, _flag, _list, _load_dotenv


def load_settings(**env) -> subprocess.CompletedProcess:
    code = ("import os; os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings';"
            "from django.conf import settings;"
            f"print(settings.DEBUG, settings.Q_CLUSTER['sync'], settings.SECRET_KEY == {DEV_SECRET_KEY!r})")
    full_env = {**os.environ, "DJANGO_DEBUG": "", "DJANGO_SECRET_KEY": "", "DJANGO_Q_SYNC": "", **env}
    return subprocess.run([sys.executable, "-c", code], cwd=settings.BASE_DIR, env=full_env,
                          capture_output=True, text=True, timeout=60)


class SecretKeyAndDebugTests(SimpleTestCase):
    def test_server_without_secret_key_refuses_to_start(self):
        result = load_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(".env.example", result.stderr)

    def test_server_with_dev_key_refuses_to_start(self):
        result = load_settings(DJANGO_SECRET_KEY=DEV_SECRET_KEY)
        self.assertNotEqual(result.returncode, 0)

    def test_server_with_own_key_runs_without_debug_and_with_background_queue(self):
        result = load_settings(DJANGO_SECRET_KEY="свой-длинный-ключ")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "False False False"), result.stderr)

    def test_debug_works_without_key_and_runs_tasks_inline(self):
        result = load_settings(DJANGO_DEBUG="1")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "True True True"), result.stderr)

    def test_q_sync_can_be_set_explicitly(self):
        result = load_settings(DJANGO_DEBUG="1", DJANGO_Q_SYNC="0")
        self.assertEqual(result.stdout.strip(), "True False True", result.stderr)

    def test_this_test_run_has_a_usable_configuration(self):
        self.assertTrue(settings.SECRET_KEY)


class EnvHelpersTests(SimpleTestCase):
    def test_flag(self):
        cases = {"1": True, "true": True, "YES": True, " on ": True, "0": False, "false": False, "x": False}
        for value, expected in cases.items():
            with self.subTest(value=value), mock.patch.dict(os.environ, {"T_FLAG": value}):
                self.assertIs(_flag("T_FLAG"), expected)

    def test_flag_default_when_not_set_or_empty(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("T_FLAG", None)
            self.assertIs(_flag("T_FLAG"), False)
            self.assertIs(_flag("T_FLAG", default=True), True)
            os.environ["T_FLAG"] = " "
            self.assertIs(_flag("T_FLAG", default=True), True)
            os.environ["T_FLAG"] = "0"
            self.assertIs(_flag("T_FLAG", default=True), False)

    def test_list(self):
        with mock.patch.dict(os.environ, {"T_LIST": " a.example , b.example,, "}):
            self.assertEqual(_list("T_LIST"), ["a.example", "b.example"])
        self.assertEqual(_list("T_LIST_NOT_SET", "x,y"), ["x", "y"])
        self.assertEqual(_list("T_LIST_NOT_SET"), [])

    def test_dotenv_is_parsed_and_does_not_override_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text(
                '\ufeff# комментарий\nT_ENV_A=1\n  T_ENV_B = "в кавычках" \nT_ENV_C=\'one\'\nстрока без равно\n'
                "\nT_ENV_KEEP=из-файла\nT_ENV_URL=postgres://u:p@h:5432/db?x=1\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"T_ENV_KEEP": "из-окружения"}):
                _load_dotenv(path)
                self.assertEqual(os.environ["T_ENV_A"], "1")
                self.assertEqual(os.environ["T_ENV_B"], "в кавычках")
                self.assertEqual(os.environ["T_ENV_C"], "one")
                self.assertEqual(os.environ["T_ENV_KEEP"], "из-окружения")
                self.assertEqual(os.environ["T_ENV_URL"], "postgres://u:p@h:5432/db?x=1")
                for key in ("T_ENV_A", "T_ENV_B", "T_ENV_C", "T_ENV_URL"):
                    del os.environ[key]

    def test_missing_dotenv_is_fine(self):
        _load_dotenv(Path("/нет/такого/.env"))