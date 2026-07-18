from pathlib import Path

from services.common.env_settings import env_int, env_str, load_dotenv

load_dotenv()

# ======Settings=========
HOST = env_str("SANDBOX_HOST", "0.0.0.0")
PORT = env_int("SANDBOX_PORT", 8003)
APP_TITLE = "sandbox"
API_KEY = env_str("API_KEY", "")

DB_ORCH_URL = env_str("DB_ORCH_URL", "http://localhost:8001")
DB_ORCH_EXPORT_TIMEOUT_SEC = env_int("DB_ORCH_EXPORT_TIMEOUT_SEC", 120)

SANDBOX_ROOT = Path(env_str("SANDBOX_ROOT", str(Path(__file__).resolve().parents[2] / "sandboxes")))
SANDBOX_MAX_FILES = env_int("SANDBOX_MAX_FILES", 5)
SANDBOX_MAX_FILE_BYTES = env_int("SANDBOX_MAX_FILE_BYTES", 5 * 1024 * 1024)
SANDBOX_EXEC_TIMEOUT_SEC = env_int("SANDBOX_EXEC_TIMEOUT_SEC", 30)
# ========================
