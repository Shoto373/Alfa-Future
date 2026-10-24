"""Наблюдаемость (SPR3-05): JSON-логи, метрики Prometheus и трассы этапов агента — без внешних SaaS.

- Логи: одна строка JSON на запись; поля запроса (request_id, хэш user_id, company_id, задержка) берутся из
  контекста запроса. Тексты новостей, профили и тела запросов в логи не пишутся.
- Метрики: счетчики и гистограммы процесса в текстовом формате Prometheus (без клиентской библиотеки);
  показатели из базы (бюджет LLM, очередь, лаг новостей, бэкап) добавляет обработчик /metrics.
- Трассы: этапы агента и вызовы инструментов — спаны OpenTelemetry с общим trace_id. trace_id пишется в
  Insight.trace (output шага) и в лог запроса; при OTEL_EXPORTER_OTLP_ENDPOINT спаны уходят в локальный
  коллектор (Tempo из профиля monitoring) по OTLP/HTTP JSON в фоновом потоке.
"""

import hashlib
import json
import logging
import os
import queue
import secrets
import threading
import time
from bisect import bisect_left
from contextvars import ContextVar

import httpx

from app import config

logger = logging.getLogger("app.observability")

# Контекст запроса: изменяемый словарь, общий для потоков обработчика (контекст копируется по ссылке).
_request: ContextVar[dict | None] = ContextVar("request_context", default=None)
SERVICE = "alfa-pulse"
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120)
STAGE_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 20, 40, 80)


# --- контекст запроса и JSON-логи ---

def start_request(request_id: str) -> dict:
    ctx = {"request_id": request_id}
    _request.set(ctx)
    return ctx


def request_context() -> dict | None:
    return _request.get()


def user_hash(user_id: str) -> str:
    """Псевдоним пользователя для логов: по нему видно действия одного человека, но не его идентификатор."""
    return hashlib.sha256(f"alfa-log:{user_id}".encode()).hexdigest()[:12]


def set_user(user_id: str) -> None:
    ctx = _request.get()
    if ctx is not None:
        ctx["user"] = user_hash(user_id)


def set_company(company_id: str | None) -> None:
    ctx = _request.get()
    if ctx is not None and company_id:
        ctx["company_id"] = str(company_id)[:64]


class JsonFormatter(logging.Formatter):
    FIELDS = ("request_id", "user", "company_id", "trace_id", "method", "path", "route", "status", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
               "level": record.levelname, "logger": record.name, "msg": record.getMessage(), "service": SERVICE}
        out |= {k: v for k, v in (_request.get() or {}).items() if k in self.FIELDS}
        out |= {k: getattr(record, k) for k in self.FIELDS if hasattr(record, k)}
        if record.exc_info:
            out["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(out, ensure_ascii=False)


def configure_logging() -> None:
    """LOG_FORMAT=json (по умолчанию) — строки JSON для сборщика логов; text — для чтения глазами."""
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    # Заменяются только обычные обработчики потока (basicConfig); перехватчики тестов и других инструментов остаются.
    root.handlers[:] = [h for h in root.handlers if type(h) is not logging.StreamHandler] + [handler]
    root.setLevel(logging.INFO)


# --- метрики процесса ---

def number(value: float) -> str:
    """Значение без потери точности: время в секундах эпохи и большие счетчики не округляются до 6 знаков."""
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _labels(names: tuple[str, ...], values: tuple) -> str:
    pairs = [f'{n}="{str(v).replace(chr(92), "/").replace(chr(34), chr(39))}"' for n, v in zip(names, values)]
    return "{" + ",".join(pairs) + "}" if pairs else ""


class Counter:
    def __init__(self, name: str, help_: str, labels: tuple[str, ...] = ()):
        self.name, self.help, self.labels = name, help_, labels
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, *values, amount: float = 1.0) -> None:
        with self._lock:
            self._values[values] = self._values.get(values, 0.0) + amount

    def value(self, *values) -> float:
        return self._values.get(values, 0.0)

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            lines += [f"{self.name}{_labels(self.labels, k)} {number(v)}" for k, v in sorted(self._values.items())]
        return lines


class Histogram:
    def __init__(self, name: str, help_: str, labels: tuple[str, ...] = (), buckets: tuple = LATENCY_BUCKETS):
        self.name, self.help, self.labels, self.buckets = name, help_, labels, buckets
        self._values: dict[tuple, list] = {}
        self._lock = threading.Lock()

    def observe(self, seconds: float, *values) -> None:
        with self._lock:
            entry = self._values.setdefault(values, [[0] * len(self.buckets), 0.0, 0])  # по корзинам, сумма, число
            idx = bisect_left(self.buckets, seconds)
            if idx < len(self.buckets):
                entry[0][idx] += 1
            entry[1] += seconds
            entry[2] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, (counts, total, n) in sorted(self._values.items()):
                running = 0
                for bound, c in zip(self.buckets, counts):
                    running += c
                    lines.append(f"{self.name}_bucket{_labels(self.labels + ('le',), key + (f'{bound:g}',))} {running}")
                lines.append(f"{self.name}_bucket{_labels(self.labels + ('le',), key + ('+Inf',))} {n}")
                lines.append(f"{self.name}_sum{_labels(self.labels, key)} {total:.6f}")
                lines.append(f"{self.name}_count{_labels(self.labels, key)} {n}")
        return lines


HTTP_REQUESTS = Counter("alfa_http_requests_total", "HTTP-запросы по маршруту и коду ответа", ("method", "route", "status"))
HTTP_LATENCY = Histogram("alfa_http_request_duration_seconds", "Время ответа HTTP по маршруту", ("route",))
AGENT_STAGE = Histogram("alfa_agent_stage_duration_seconds", "Длительность этапов агента", ("stage",), STAGE_BUCKETS)
INSIGHTS = Counter("alfa_insights_total", "Построенные разборы по режиму и причине отката к правилам", ("mode", "fallback"))
CHECKS = Counter("alfa_agent_check_failures_total", "Непройденные проверки черновика агента", ("check",))
CACHE = Counter("alfa_cache_requests_total", "Обращения к общему кэшу", ("result",))
REGISTRY = (HTTP_REQUESTS, HTTP_LATENCY, AGENT_STAGE, INSIGHTS, CHECKS, CACHE)


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.inc(method, route, str(status))
    HTTP_LATENCY.observe(seconds, route)


def cache_lookup(hit: bool) -> None:
    CACHE.inc("hit" if hit else "miss")


def render() -> list[str]:
    return [line for metric in REGISTRY for line in metric.render()]


# --- трассы ---

def new_trace_id() -> str:
    return secrets.token_hex(16)


def _span(trace_id: str, parent: str | None, name: str, start_ns: int, end_ns: int, attrs: dict, error: bool) -> dict:
    return {"traceId": trace_id, "spanId": secrets.token_hex(8), **({"parentSpanId": parent} if parent else {}),
            "name": name, "kind": 1, "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(end_ns),
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items() if v is not None],
            "status": {"code": 2 if error else 1}}


def record_insight(insight: dict, started: float, request_id: str | None = None) -> str | None:
    """Наблюдаемость не должна ломать разбор: сбой здесь только пишется в лог."""
    try:
        return _record_insight(insight, started, request_id)
    except Exception:  # noqa: BLE001
        logger.exception("insight telemetry failed")
        return None


def _record_insight(insight: dict, started: float, request_id: str | None = None) -> str:
    """Метрики и спаны готового разбора: корневой спан «insight» и по спану на каждый шаг трассы агента.
    trace_id дописывается в output каждого шага (Insight.trace) — по нему разбор в интерфейсе связан с логами."""
    trace_id = new_trace_id()
    ctx = _request.get()
    if ctx is not None:
        ctx["trace_id"] = trace_id
    start_ns, now_ns = int(started * 1e9), time.time_ns()
    root = _span(trace_id, None, "insight", start_ns, now_ns, {"insight.mode": insight.get("mode"), "request_id": request_id,
                                                                 "fallback": insight.get("fallback_reason")}, False)
    spans, cursor = [root], start_ns
    for step in insight.get("trace") or []:
        seconds = float(step.get("duration_ms") or 0) / 1000
        AGENT_STAGE.observe(seconds, step.get("stage", "unknown"))
        if step.get("stage") == "check" and step.get("status") in ("warning", "error"):
            CHECKS.inc(step.get("name", "unknown"))
        end = cursor + int(seconds * 1e9)
        spans.append(_span(trace_id, root["spanId"], f"{step.get('stage')}: {step.get('name')}", cursor, end,
                           {"agent.stage": step.get("stage"), "agent.status": step.get("status")}, step.get("status") == "error"))
        step["output"] = {**(step.get("output") or {}), "trace_id": trace_id}
        cursor = end
    INSIGHTS.inc(insight.get("mode", "unknown"), insight.get("fallback_reason") or "none")
    export(spans)
    return trace_id


_spans: queue.Queue = queue.Queue(maxsize=2000)
_exporter: threading.Thread | None = None


def export(spans: list[dict]) -> None:
    """Спаны — в очередь фонового экспорта (если задан коллектор); полная очередь — спаны отбрасываются."""
    if not config.otlp_endpoint():
        return
    _ensure_exporter()
    for span in spans:
        try:
            _spans.put_nowait(span)
        except queue.Full:
            return


def _ensure_exporter() -> None:
    global _exporter
    if _exporter is None or not _exporter.is_alive():
        _exporter = threading.Thread(target=_export_loop, name="otlp-exporter", daemon=True)
        _exporter.start()


def _export_loop() -> None:
    while True:
        batch = [_spans.get()]
        while len(batch) < 200:
            try:
                batch.append(_spans.get(timeout=1.0))
            except queue.Empty:
                break
        body = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": SERVICE}}]},
                                   "scopeSpans": [{"scope": {"name": "app.agent"}, "spans": batch}]}]}
        try:
            httpx.post(f"{config.otlp_endpoint()}/v1/traces", json=body, timeout=5.0)
        except httpx.HTTPError as exc:  # коллектор недоступен — трассы теряются, сервис работает
            logger.warning("otlp export failed: %s", type(exc).__name__)
