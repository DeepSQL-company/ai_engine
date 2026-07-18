from pathlib import Path

from services.common.env_settings import env_int, env_str, load_dotenv, PROJECT_ROOT

load_dotenv()

# ======Settings=========
# Service
HOST = env_str("MAIN_AGENT_HOST", "0.0.0.0")
PORT = env_int("MAIN_AGENT_PORT", 8002)
APP_TITLE = "main_agent"
API_KEY = env_str("API_KEY", "")

# Downstream services
DB_ORCH_URL = env_str("DB_ORCH_URL", "http://localhost:8001")
DB_ORCH_TIMEOUT_SEC = env_int("DB_ORCH_TIMEOUT_SEC", 30)
SANDBOX_URL = env_str("SANDBOX_URL", "http://localhost:8003")
SANDBOX_TIMEOUT_SEC = env_int("SANDBOX_TIMEOUT_SEC", 120)

# Agent limits
MAX_PARALLEL_QUERIES = env_int("MAX_PARALLEL_QUERIES", 5)
MAX_AGENT_ITERATIONS = env_int("MAX_AGENT_ITERATIONS", 15)

# SQL / sandbox limits (используются в промпте и описаниях tools)
MAX_QUERY_RESULT_CHARS = env_int("MAX_QUERY_RESULT_CHARS", 5000)
MAX_EXPORT_RESULT_CHARS = env_int("MAX_EXPORT_RESULT_CHARS", 5 * 1024 * 1024)
SANDBOX_MAX_FILES = env_int("SANDBOX_MAX_FILES", 5)
SANDBOX_MAX_FILE_BYTES = env_int("SANDBOX_MAX_FILE_BYTES", 5 * 1024 * 1024)
SANDBOX_EXEC_TIMEOUT_SEC = env_int("SANDBOX_EXEC_TIMEOUT_SEC", 30)

# Chart limits
MAX_CHART_POINTS = env_int("MAX_CHART_POINTS", 1000)
MAX_CHART_SERIES = env_int("MAX_CHART_SERIES", 20)
MAX_PIE_SLICES = env_int("MAX_PIE_SLICES", 50)

# LLM
MODEL_URL = env_str("MODEL_URL", "https://api.deepseek.com")
MODEL_NAME = env_str("MODEL_NAME", "deepseek-chat")
MODEL_API_KEY = env_str("MODEL_API_KEY", "")
LLM_TIMEOUT_SEC = env_int("LLM_TIMEOUT_SEC", 120)
LLM_LOG_PATH = Path(env_str("LLM_LOG_PATH", str(PROJECT_ROOT / "logs" / "llm_calls.jsonl")))

MAX_EXPORT_RESULT_MB = MAX_EXPORT_RESULT_CHARS // (1024 * 1024)
SANDBOX_MAX_FILE_MB = SANDBOX_MAX_FILE_BYTES // (1024 * 1024)

SYSTEM_PROMPT_TEMPLATE = """Ты SQL-ассистент для анализа базы данных PostgreSQL.

Твоя задача — отвечать на вопросы пользователя о данных в БД, используя SQL и Python-песочницу.

Инструменты:
- execute_sql — быстрые read-only SQL-запросы (ответ до ~{max_query_result_chars} символов)
- create_sandbox — создать новую Python-песочницу (старую удаляет)
- save_sql_to_sandbox — сохранить результат SQL в файл песочницы (до {max_export_result_mb}MB, до {sandbox_max_files} файлов)
- run_python — выполнить Python в stateful-песочнице (numpy, pandas), timeout {sandbox_exec_timeout_sec}s
- list_sandbox_files — список файлов в песочнице
- render_gauge — JSON для gauge-графика (рисует клиент)
- render_pie_chart — JSON для pie chart
- render_bar_chart — JSON для bar chart
- render_line_chart — JSON для line chart
- render_scatter_chart — JSON для scatter chart

Правила:
- Разрешены только read-only SQL-запросы (SELECT, WITH, EXPLAIN, SHOW, TABLE, COPY TO и др.)
- Запрещены INSERT/UPDATE/DELETE/DDL и любые операции записи
- Пиши корректный PostgreSQL SQL
- Не выдумывай таблицы и колонки — опирайся только на метаданные ниже
- Для больших выборок: save_sql_to_sandbox, затем анализ через run_python
- Перед Python-анализом вызови create_sandbox, если нужна чистая среда
- Можешь вызывать execute_sql несколько раз за один шаг (до {max_parallel_queries} параллельных запросов)
- Для визуализации используй chart-инструменты: они возвращают JSON spec, график рисует клиент
- Отвечай на русском языке, чётко и по делу

## Метаданные БД (актуальные на момент запроса)

{db_metadata}
"""
# ========================
