import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


def database_settings(**env) -> dict:
    code = ("import os, json; os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings';"
            "from django.conf import settings; print(json.dumps(settings.DATABASES['default'], default=str))")
    full_env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    full_env.update({"DJANGO_DEBUG": "1", **env})
    result = subprocess.run([sys.executable, "-c", code], cwd=settings.BASE_DIR, env=full_env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class SqliteConcurrencyTests(SimpleTestCase):
    def test_sqlite_takes_the_write_lock_up_front_and_waits_for_it(self):
        options = database_settings(DATABASE_URL="sqlite:///test.sqlite3")["OPTIONS"]
        self.assertEqual((options["transaction_mode"], options["timeout"]), ("IMMEDIATE", 30))

    def test_default_database_is_sqlite_with_the_same_options(self):
        config = database_settings()
        self.assertTrue(config["ENGINE"].endswith("sqlite3"))
        self.assertEqual(config["OPTIONS"]["transaction_mode"], "IMMEDIATE")

    def test_postgres_gets_no_sqlite_options(self):
        config = database_settings(DATABASE_URL="postgres://user:pass@localhost:5432/shop")
        self.assertNotIn("transaction_mode", config.get("OPTIONS", {}))
