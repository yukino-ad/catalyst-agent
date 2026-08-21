from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.domain.cluster_readonly_preflight import ClusterReadonlySettings
from app.domain.cluster_transport import ClusterTransport
from tools.llm_client import LLMSettings, OpenAICompatibleClient


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def web_remote_operations_enabled() -> bool:
    return truthy(os.getenv("WEB_REMOTE_OPERATIONS_ENABLED", "false"))


class ConnectionStatusService:
    """Expose sanitized configuration and opt-in live connectivity checks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_result: dict[str, Any] | None = None

    def configured_status(self) -> dict[str, Any]:
        if self._last_result is not None:
            return dict(self._last_result)
        return self._build_status(check_live=False)

    def check(self) -> dict[str, Any]:
        with self._lock:
            self._last_result = self._build_status(check_live=True)
            return dict(self._last_result)

    def _build_status(self, check_live: bool) -> dict[str, Any]:
        llm = LLMSettings.load()
        cluster = ClusterReadonlySettings.from_environment()
        kimi_configured = llm.ready
        cluster_configured = bool(
            cluster.host
            and cluster.user
            and cluster.key_path.is_file()
            and cluster.known_hosts_path.is_file()
        )
        result: dict[str, Any] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "kimi": self._base_connection(
                f"Kimi ({llm.model})", kimi_configured, check_live
            ),
            "cluster": self._base_connection("HPC", cluster_configured, check_live),
            "remote_operations": {
                "web_enabled": web_remote_operations_enabled(),
                "upload_enabled": truthy(os.getenv("CLUSTER_REMOTE_WRITE_ENABLED")),
                "submission_enabled": truthy(os.getenv("CLUSTER_SUBMISSION_ENABLED")),
            },
        }
        if not check_live:
            return result
        if kimi_configured:
            result["kimi"] = self._check_kimi()
        if cluster_configured:
            result["cluster"] = self._check_cluster(cluster)
        return result

    @staticmethod
    def _base_connection(label: str, configured: bool, checking: bool) -> dict[str, Any]:
        if not configured:
            return {
                "configured": False,
                "status": "not_configured",
                "label": label,
                "detail": "尚未完成配置",
            }
        return {
            "configured": True,
            "status": "checking" if checking else "configured_not_checked",
            "label": label,
            "detail": "正在检查连接" if checking else "已配置，尚未检查连接",
        }

    @staticmethod
    def _check_kimi() -> dict[str, Any]:
        settings = LLMSettings.load()
        label = f"Kimi ({settings.model})"
        try:
            OpenAICompatibleClient(settings).chat(
                [
                    {"role": "system", "content": "你是连接检查助手。"},
                    {"role": "user", "content": "只回复 OK"},
                ],
                temperature=1.0,
                max_tokens=2048,
                timeout_seconds=45,
            )
            return {
                "configured": True,
                "status": "connected",
                "label": label,
                "detail": "API 请求成功",
            }
        except Exception as error:
            return {
                "configured": True,
                "status": "failed",
                "label": label,
                "detail": _safe_error(error),
            }

    @staticmethod
    def _check_cluster(settings: ClusterReadonlySettings) -> dict[str, Any]:
        try:
            output = ClusterTransport(settings).run(
                "printf catalyst-agent-connected",
                timeout=min(max(settings.timeout_seconds, 1), 20),
            )
            if output.strip() != "catalyst-agent-connected":
                raise RuntimeError("SSH 探针返回内容不符合预期")
            return {
                "configured": True,
                "status": "connected",
                "label": "HPC",
                "detail": "SSH 只读连接成功",
            }
        except Exception as error:
            return {
                "configured": True,
                "status": "failed",
                "label": "HPC",
                "detail": _safe_error(error),
            }


def _safe_error(error: Exception) -> str:
    text = str(error).replace("\r", " ").replace("\n", " ").strip()
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "连接超时，请检查网络、代理或登录节点"
    if "permission denied" in lowered or "authentication" in lowered:
        return "认证失败，请检查密钥和账号配置"
    if "http 401" in lowered or "http 403" in lowered:
        return "API 认证失败，请检查密钥"
    if "http 429" in lowered:
        return "API 当前限流，请稍后重试"
    if "not found" in lowered:
        return "本机缺少连接程序或配置文件"
    detail = text[:180] or type(error).__name__
    sensitive_values = (
        os.getenv("LLM_API_KEY", "").strip(),
        os.getenv("LLM_BASE_URL", "").strip(),
        os.getenv("CLUSTER_SSH_HOST", "").strip(),
        os.getenv("CLUSTER_SSH_USER", "").strip(),
        os.getenv("CLUSTER_SSH_KEY_PATH", "").strip(),
        os.getenv("CLUSTER_SSH_KNOWN_HOSTS", "").strip(),
    )
    for sensitive in sensitive_values:
        if sensitive:
            detail = detail.replace(sensitive, "***")
    return detail
