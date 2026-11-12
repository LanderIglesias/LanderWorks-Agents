import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

DAILY_MSG = "Límite diario de análisis alcanzado, vuelve mañana"
BUDGET_MSG = "Demo temporalmente fuera de servicio por límite de presupuesto"
CACHE_TTL = timedelta(hours=24)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, count INT);
CREATE TABLE IF NOT EXISTS reservations(
    id TEXT PRIMARY KEY, month TEXT, reserved_usd REAL, settled_usd REAL NULL, created TEXT);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, report TEXT, created TEXT);
"""


class LimitExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def cache_key(owner: str, repo: str, head_sha: str) -> str:
    raw = f"github.com/{owner.lower()}/{repo.lower()}@{head_sha}"
    return hashlib.sha256(raw.encode()).hexdigest()


def default_db_path() -> Path:
    env = os.getenv("TECH_DEBT_DB_PATH")
    return Path(env) if env else _REPO_ROOT / "backend" / "data" / "tech_debt.sqlite3"


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


def _check_cost(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError("el coste debe ser finito y >= 0")


class CostGuard:
    def __init__(
        self,
        db_path: Path,
        daily_limit: int = 20,
        monthly_budget_eur: float = 20.0,
        # el valor por defecto lee la variable de entorno al importar el módulo
        eur_per_usd: float = float(os.getenv("TECH_DEBT_EUR_PER_USD", "0.92")),
    ):
        self.db_path = Path(db_path)
        self.daily_limit = daily_limit
        self.monthly_budget_eur = monthly_budget_eur
        self.eur_per_usd = eur_per_usd
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def reserve(self, max_cost_usd: float, now: datetime | None = None) -> str:
        _check_cost(max_cost_usd)
        moment = _utc(now)
        day, month = moment.strftime("%Y-%m-%d"), moment.strftime("%Y-%m")
        with _LOCK, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT count FROM usage WHERE day=?", (day,)).fetchone()
                if row and row[0] >= self.daily_limit:
                    raise LimitExceeded(DAILY_MSG)
                spent_usd = conn.execute(
                    "SELECT COALESCE(SUM(COALESCE(settled_usd, reserved_usd)), 0)"
                    " FROM reservations WHERE month=?",
                    (month,),
                ).fetchone()[0]
                if (spent_usd + max_cost_usd) * self.eur_per_usd > self.monthly_budget_eur:
                    raise LimitExceeded(BUDGET_MSG)
                conn.execute(
                    "INSERT INTO usage(day, count) VALUES(?, 1)"
                    " ON CONFLICT(day) DO UPDATE SET count = count + 1",
                    (day,),
                )
                # una reserva huérfana sin settle/release se queda contada al máximo: tras una
                # caída puede haberse gastado dinero, así que sobrecontar es el lado seguro
                rid = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO reservations VALUES(?, ?, ?, NULL, ?)",
                    (rid, month, max_cost_usd, moment.isoformat()),
                )
                conn.execute("COMMIT")
                return rid
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def _settle(self, reservation_id: str, cost_usd: float) -> None:
        _check_cost(cost_usd)
        with _LOCK, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE reservations SET settled_usd=? WHERE id=? AND settled_usd IS NULL",
                (cost_usd, reservation_id),
            )

    def settle(self, reservation_id: str, actual_cost_usd: float) -> None:
        self._settle(reservation_id, actual_cost_usd)

    def release(self, reservation_id: str) -> None:
        self._settle(reservation_id, 0.0)

    def get_cached(self, key: str, now: datetime | None = None) -> dict | None:
        moment = _utc(now)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT report, created FROM cache WHERE key=?", (key,)).fetchone()
        if not row or moment - datetime.fromisoformat(row[1]) >= CACHE_TTL:
            return None
        return json.loads(row[0])

    def put_cached(self, key: str, report: dict, now: datetime | None = None) -> None:
        with _LOCK, closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache VALUES(?, ?, ?)",
                (key, json.dumps(report, ensure_ascii=False), _utc(now).isoformat()),
            )
