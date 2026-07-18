from pathlib import Path

from services.common.env_settings import env_bool, env_int, env_str, load_dotenv

load_dotenv()

# ======Settings=========
HOST = env_str("DB_ORCH_HOST", "0.0.0.0")
PORT = env_int("DB_ORCH_PORT", 8001)
APP_TITLE = "db_orch"
API_KEY = env_str("API_KEY", "")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "db.local.yaml"

MAX_QUERY_RESULT_CHARS = env_int("MAX_QUERY_RESULT_CHARS", 5000)
MAX_EXPORT_RESULT_CHARS = env_int("MAX_EXPORT_RESULT_CHARS", 5 * 1024 * 1024)
READONLY_QUERIES = env_bool("DB_READONLY", True)
# ========================
