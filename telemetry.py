"""
万象积木 — 可观测性模块

功能:
1. 性能追踪 — 关键操作耗时统计
2. 调用计数 — 路由/LLM/记忆检索调用量
3. 错误追踪 — 按类型统计错误
4. 可选 OpenTelemetry 集成

用法:
    from telemetry import tracer
    with tracer.span("route") as span:
        result = engine.route(message)
"""

from __future__ import annotations

import time
import logging
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """单个指标数据点"""
    name: str
    value: float
    tags: dict = field(default_factory=dict)
    timestamp: float = 0.0


class MetricsCollector:
    """轻量级指标收集器（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._errors: dict[str, int] = defaultdict(int)
        self._points: list[MetricPoint] = []

    def incr(self, name: str, tags: dict = None):
        """增加计数器"""
        key = name + (str(tags) if tags else "")
        with self._lock:
            self._counters[key] += 1

    def record_latency(self, name: str, value_ms: float):
        """记录延迟（毫秒）"""
        with self._lock:
            self._latencies[name].append(value_ms)
            self._points.append(MetricPoint(name=f"{name}_latency", value=value_ms, timestamp=time.time()))

    def record_error(self, error_type: str):
        """记录错误"""
        with self._lock:
            self._errors[error_type] += 1

    def get_stats(self) -> dict:
        """获取统计摘要"""
        with self._lock:
            lat_summary = {}
            for name, vals in self._latencies.items():
                if vals:
                    lat_summary[name] = {
                        "count": len(vals),
                        "avg_ms": round(sum(vals) / len(vals), 1),
                        "max_ms": round(max(vals), 1),
                        "min_ms": round(min(vals), 1),
                        "p95_ms": round(sorted(vals)[int(len(vals) * 0.95)], 1) if len(vals) > 20 else round(max(vals), 1),
                    }
            return {
                "counters": dict(self._counters),
                "latencies": lat_summary,
                "errors": dict(self._errors),
                "total_points": len(self._points),
            }

    def reset(self):
        """重置所有指标"""
        with self._lock:
            self._counters.clear()
            self._latencies.clear()
            self._errors.clear()
            self._points.clear()


# 全局指标收集器
metrics = MetricsCollector()


class Tracer:
    """
    性能追踪器

    用法:
        with tracer.span("route") as span:
            span.set_tag("task_type", "code")
            result = engine.route(message)
    """

    def __init__(self, name: str = "wanxiang-jimu"):
        self.name = name
        self._otel_tracer = None
        self._init_otel()

    def _init_otel(self):
        """尝试初始化 OpenTelemetry"""
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource

            resource = Resource.create({"service.name": self.name})
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(provider)
            self._otel_tracer = trace.get_tracer(self.name)
            logger.info("OpenTelemetry 已初始化")
        except ImportError:
            self._otel_tracer = None
        except Exception as e:
            self._otel_tracer = None
            logger.debug(f"OpenTelemetry 初始化失败（非致命）: {e}")

    @contextmanager
    def span(self, name: str, tags: dict = None, record_metrics: bool = True):
        """创建追踪 span"""
        start = time.time()
        err = None
        try:
            yield self._SpanContext(name, tags)
        except Exception as e:
            err = e
            raise
        finally:
            elapsed = (time.time() - start) * 1000
            if record_metrics:
                metrics.incr(f"span.{name}")
                metrics.record_latency(f"span.{name}", elapsed)
                if err:
                    metrics.record_error(type(err).__name__)
            logger.debug(f"[tracer] {name}: {elapsed:.1f}ms{' ERROR: ' + str(err) if err else ''}")

    class _SpanContext:
        def __init__(self, name, tags=None):
            self.name = name
            self.tags = tags or {}

        def set_tag(self, key, value):
            self.tags[key] = value


# 全局追踪器
tracer = Tracer()


def get_trace_summary() -> dict:
    """获取追踪摘要"""
    return metrics.get_stats()


def reset_trace():
    """重置追踪数据"""
    metrics.reset()
