# -*- coding: utf-8 -*-
"""统一代理解析。优先级：脚本专属 > AUTO_TASK_PROXY > 系统 https_proxy。"""
import os


def resolve_proxy(*specific_env_names, use_unified=True, use_system=True):
    for name in specific_env_names:
        value = os.environ.get(name) or os.environ.get(name.lower())
        if value:
            return value.strip()

    if use_unified:
        value = os.environ.get("AUTO_TASK_PROXY") or os.environ.get("auto_task_proxy")
        if value:
            return value.strip()

    if use_system:
        for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
            value = os.environ.get(key)
            if value:
                return value.strip()

    return ""


def requests_proxies(proxy_url):
    if not proxy_url:
        return {}
    return {"http": proxy_url, "https": proxy_url}


def apply_to_env(env, proxy_url):
    """给 curl/subprocess 用：写入 http(s)_proxy。"""
    if not proxy_url:
        return env
    env = dict(env)
    env["http_proxy"] = proxy_url
    env["https_proxy"] = proxy_url
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    return env
