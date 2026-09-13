"""Guardian 参数校验：read_file 路径与 web_fetch URL 的安全边界。

被工具自身（防御性二次校验）与 GuardianMiddleware（执行前拦截）共用。
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_web_fetch_allowed_domains

logger = logging.getLogger(__name__)


class GuardError(Exception):
    """参数被安全策略拒绝。"""


# ── read_file 路径校验 ──

# 目录名黑名单：命中任意一层目录即拒绝（不区分大小写）
_SENSITIVE_DIR_NAMES = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".azure",
    ".terraform.d",
}

# 文件名黑名单（精确匹配）
_SENSITIVE_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".bash_history",
    ".zsh_history",
    ".python_history",
    ".wgetrc",
    ".curlrc",
    "credentials",
    "kubeconfig",
    "albert-agent-config.json",  # 内含模型 API Key
}

# 文件名前缀/后缀黑名单
_SENSITIVE_FILE_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa")
_SENSITIVE_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


def _allowed_read_roots() -> list[Path]:
    """允许读取的根目录：用户主目录 + 进程工作目录。"""
    roots: list[Path] = []
    for root in (Path.home(), Path.cwd()):
        try:
            roots.append(root.resolve())
        except OSError:
            continue
    return roots


def _sensitive_reason(resolved: Path) -> str | None:
    """命中敏感目录/文件时返回原因，否则返回 None。"""
    for part in resolved.parts:
        if part.lower() in _SENSITIVE_DIR_NAMES:
            return f"敏感目录 {part}"
    name = resolved.name.lower()
    if (
        name in _SENSITIVE_FILE_NAMES
        or name.startswith(_SENSITIVE_FILE_PREFIXES)
        or name.endswith(_SENSITIVE_FILE_SUFFIXES)
        or "credential" in name
    ):
        return f"敏感文件 {resolved.name}"
    return None


def validate_read_path(
    path: str, *, roots: Iterable[Path] | None = None
) -> Path:
    """校验 read_file 的路径并返回解析后的绝对路径。

    规则：先 expanduser/resolve（符号链接会被解析到真实路径），必须位于
    允许根目录（默认家目录 + 工作目录）内，且不命中敏感目录/文件黑名单。
    不合法时抛 GuardError。
    """
    if not isinstance(path, str) or not path.strip():
        raise GuardError("路径为空")

    try:
        resolved = Path(path).expanduser().resolve()
    except OSError as exc:
        raise GuardError(f"路径无法解析：{exc}") from exc

    allowed = [
        root.resolve() for root in (roots if roots is not None else _allowed_read_roots())
    ]
    if not any(
        resolved == root or resolved.is_relative_to(root) for root in allowed
    ):
        raise GuardError("路径不在允许的目录范围内（仅限用户主目录与工作目录）")

    reason = _sensitive_reason(resolved)
    if reason is not None:
        raise GuardError(f"拒绝访问{reason}")
    return resolved


# ── web_fetch URL 校验 ──


def is_domain_allowed(host: str, domains: Sequence[str]) -> bool:
    """域名白名单匹配：精确匹配或子域匹配（example.com 放行 a.example.com）。"""
    normalized_host = host.lower().rstrip(".")
    for domain in domains:
        normalized = domain.lower().strip(".")
        if normalized and (
            normalized_host == normalized
            or normalized_host.endswith("." + normalized)
        ):
            return True
    return False


def validate_fetch_url(url: str, *, domains: Sequence[str] | None = None) -> str:
    """校验 web_fetch 的 URL：https、白名单域名、非本机/IP、无用户信息、仅 443。

    返回原 URL（已 strip）；不合法时抛 GuardError。白名单为空表示全部拒绝。
    """
    if not isinstance(url, str) or not url.strip():
        raise GuardError("URL 为空")

    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise GuardError("仅允许 https 访问")
    if parts.username or parts.password:
        raise GuardError("URL 不允许携带用户名/密码")
    try:
        port = parts.port
    except ValueError as exc:
        raise GuardError("URL 端口非法") from exc
    if port not in (None, 443):
        raise GuardError("仅允许访问 443 端口")

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise GuardError("URL 缺少主机名")
    if host == "localhost" or host.endswith(".localhost"):
        raise GuardError("不允许访问本机地址")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise GuardError("不允许直接访问 IP 地址")

    allowed = tuple(domains) if domains is not None else get_web_fetch_allowed_domains()
    if not allowed:
        raise GuardError("未配置 webFetchAllowedDomains 白名单，禁止访问任何地址")
    if not is_domain_allowed(host, allowed):
        raise GuardError(f"域名 {host} 不在白名单内")
    return url.strip()
