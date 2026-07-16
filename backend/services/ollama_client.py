"""Ollama API client with structured error codes and diagnostics."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import requests

from config import get_config


class OllamaErrorCode:
    OFFLINE = "OLLAMA_OFFLINE"
    TIMEOUT = "OLLAMA_TIMEOUT"
    HTTP_ERROR = "OLLAMA_HTTP_ERROR"
    INVALID_RESPONSE = "OLLAMA_INVALID_RESPONSE"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    EMPTY_RESPONSE = "OLLAMA_EMPTY_RESPONSE"


class OllamaError(Exception):
    def __init__(self, message: str, error_code: str = OllamaErrorCode.HTTP_ERROR,
                 status_code: int | None = None, raw_response: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.raw_response = raw_response


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout_sec: int | None = None) -> None:
        cfg = get_config().get("ollama", {})
        self._base_url = (base_url or cfg.get("baseUrl", "http://127.0.0.1:11434")).rstrip("/")
        self._model = model or cfg.get("model", "qwen3:4b-instruct")
        self._timeout = timeout_sec or cfg.get("timeoutSec", 300)

    def chat(
        self, system_prompt: str, user_prompt: str, *,
        model: str | None = None, temperature: float = 0.0,
        num_predict: int = 4096,
        keep_alive: str | None = None,
        format_json: bool = True,
    ) -> dict[str, Any]:
        """
        Send a chat request to Ollama.
        keep_alive: duration string like "30m" to keep model loaded after generation.
        """
        use_model = model or self._model
        url = f"{self._base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if format_json:
            payload["format"] = "json"
        if keep_alive:
            payload["keep_alive"] = keep_alive

        start = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=(15, self._timeout))
        except requests.ConnectionError:
            raise OllamaError(
                f"Ollama 服务未启动 ({self._base_url})。请确认 Ollama 已运行。",
                error_code=OllamaErrorCode.OFFLINE,
            )
        except requests.Timeout:
            raise OllamaError(
                f"Ollama 生成超时（{self._timeout}秒）。模型 {use_model} 响应过慢。",
                error_code=OllamaErrorCode.TIMEOUT,
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code != 200:
            detail = resp.text[:500]
            if "not found" in detail.lower():
                raise OllamaError(
                    f"未找到模型 {use_model}。请执行: ollama pull {use_model}",
                    error_code=OllamaErrorCode.MODEL_NOT_FOUND,
                    status_code=resp.status_code, raw_response=detail,
                )
            raise OllamaError(
                f"Ollama 返回 HTTP {resp.status_code}: {detail}",
                error_code=OllamaErrorCode.HTTP_ERROR,
                status_code=resp.status_code, raw_response=detail,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise OllamaError(
                "Ollama 返回的不是合法 JSON。",
                error_code=OllamaErrorCode.INVALID_RESPONSE,
                raw_response=resp.text[:1000],
            )

        message = data.get("message", {})
        content = message.get("content", "")
        # qwen3-vl models may output all content in the thinking field
        if not content or not content.strip():
            thinking = message.get("thinking", "")
            if thinking and thinking.strip():
                content = thinking.strip()
        if not content or not content.strip():
            raise OllamaError(
                "Ollama 返回空内容。",
                error_code=OllamaErrorCode.EMPTY_RESPONSE,
                raw_response=json.dumps(data, ensure_ascii=False),
            )

        return {
            "content": content.strip(), "model": data.get("model", use_model),
            "total_duration_ns": data.get("total_duration", 0),
            "eval_count": data.get("eval_count", 0),
            "eval_duration_ns": data.get("eval_duration", 0),
            "generation_latency_ms": elapsed_ms,
            "raw_response": data,
        }

    def chat_with_images(
        self, system_prompt: str, user_prompt: str, *,
        image_paths: list[str] | None = None,
        image_bytes_list: list[bytes] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        num_predict: int = 1500,
        keep_alive: str | None = None,
        format_json: bool = True,
        timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        """
        Send a multimodal chat request to Ollama with images.

        Images can be provided as file paths (image_paths) or raw bytes (image_bytes_list).
        Images are sent as base64-encoded data URIs in the 'images' field.

        Returns same dict shape as chat(): content, model, timing data.
        """
        use_model = model or self._model
        url = f"{self._base_url}/api/chat"
        timeout = timeout_sec or self._timeout

        # Build messages with images
        images_b64: list[str] = []

        # Process file paths
        if image_paths:
            for img_path in image_paths:
                p = Path(img_path)
                if not p.exists():
                    raise OllamaError(
                        f"图片文件不存在: {img_path}",
                        error_code="VISUAL_IMAGE_NOT_FOUND",
                    )
                raw = p.read_bytes()
                images_b64.append(base64.b64encode(raw).decode("ascii"))

        # Process raw bytes
        if image_bytes_list:
            for img_bytes in image_bytes_list:
                images_b64.append(base64.b64encode(img_bytes).decode("ascii"))

        # Build the user message with images
        user_message: dict[str, Any] = {
            "role": "user",
            "content": user_prompt,
        }
        if images_b64:
            user_message["images"] = images_b64

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                user_message,
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if format_json:
            payload["format"] = "json"
        if keep_alive:
            payload["keep_alive"] = keep_alive

        start = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, timeout=(15, timeout))
        except requests.ConnectionError:
            raise OllamaError(
                f"Ollama 服务未启动 ({self._base_url})。请确认 Ollama 已运行。",
                error_code=OllamaErrorCode.OFFLINE,
            )
        except requests.Timeout:
            raise OllamaError(
                f"Ollama 视觉生成超时（{timeout}秒）。模型 {use_model} 响应过慢。",
                error_code=OllamaErrorCode.TIMEOUT,
            )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code != 200:
            detail = resp.text[:500]
            if "not found" in detail.lower():
                raise OllamaError(
                    f"未找到模型 {use_model}。请执行: ollama pull {use_model}",
                    error_code="VISUAL_MODEL_NOT_FOUND",
                    status_code=resp.status_code, raw_response=detail,
                )
            raise OllamaError(
                f"Ollama 返回 HTTP {resp.status_code}: {detail}",
                error_code=OllamaErrorCode.HTTP_ERROR,
                status_code=resp.status_code, raw_response=detail,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise OllamaError(
                "Ollama 返回的不是合法 JSON。",
                error_code=OllamaErrorCode.INVALID_RESPONSE,
                raw_response=resp.text[:1000],
            )

        message = data.get("message", {})
        content = message.get("content", "")
        # qwen3-vl models may output all content in the thinking field
        if not content or not content.strip():
            thinking = message.get("thinking", "")
            if thinking and thinking.strip():
                content = thinking.strip()
        if not content or not content.strip():
            raise OllamaError(
                "Ollama 返回空内容。",
                error_code=OllamaErrorCode.EMPTY_RESPONSE,
                raw_response=json.dumps(data, ensure_ascii=False),
            )

        return {
            "content": content.strip(), "model": data.get("model", use_model),
            "total_duration_ns": data.get("total_duration", 0),
            "load_duration_ns": data.get("load_duration", 0),
            "prompt_eval_duration_ns": data.get("prompt_eval_duration", 0),
            "eval_count": data.get("eval_count", 0),
            "eval_duration_ns": data.get("eval_duration", 0),
            "generation_latency_ms": elapsed_ms,
            "raw_response": data,
        }

    def unload_model(self, model: str | None = None) -> dict[str, Any]:
        """
        Explicitly unload a model from VRAM using keep_alive=0.
        Sends a minimal chat request to trigger immediate unload after response.
        Returns timing and success status.
        """
        use_model = model or self._model
        url = f"{self._base_url}/api/generate"
        start = time.perf_counter()
        try:
            resp = requests.post(url, json={
                "model": use_model,
                "prompt": "ok",
                "keep_alive": 0,
                "stream": False,
                "options": {"num_predict": 1},
            }, timeout=(5, 10))
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            ok = resp.status_code == 200
            return {
                "success": ok,
                "model": use_model,
                "unload_ms": elapsed_ms,
                "message": "Model unload request sent" if ok else f"HTTP {resp.status_code}",
            }
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "success": False,
                "model": use_model,
                "unload_ms": elapsed_ms,
                "message": str(e)[:200],
            }

    def list_running_models(self) -> dict[str, Any]:
        """List currently loaded models via GET /api/ps."""
        url = f"{self._base_url}/api/ps"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return {"available": False, "models": [], "error": f"HTTP {resp.status_code}"}
            data = resp.json()
            models_list = data.get("models", [])
            return {
                "available": True,
                "models": [
                    {
                        "name": m.get("name", ""),
                        "model": m.get("model", ""),
                        "size_vram": m.get("size_vram", 0),
                        "expires_at": m.get("expires_at", ""),
                    }
                    for m in models_list
                ],
            }
        except Exception as e:
            return {"available": False, "models": [], "error": str(e)[:200]}

    def health_check(self) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return {"available": False, "model": self._model, "model_present": False,
                        "last_error": f"HTTP {resp.status_code}"}
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            model_present = any(self._model in m for m in models)
            return {"available": True, "model": self._model, "model_present": model_present,
                    "last_error": None if model_present else f"Model '{self._model}' not in ollama list"}
        except Exception as e:
            return {"available": False, "model": self._model, "model_present": False,
                    "last_error": str(e)[:200]}

    def diagnostic_inference(self) -> dict[str, Any]:
        result = {
            "available": False, "base_url": self._base_url,
            "configured_model": self._model, "model_present": False,
            "inference_ok": False, "latency_ms": 0,
            "error_code": None, "message": "",
        }
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                result["error_code"] = "OLLAMA_HTTP_ERROR"
                result["message"] = f"GET /api/tags returned {resp.status_code}"
                return result
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            result["available"] = True
            result["model_present"] = any(self._model in m for m in models)
            if not result["model_present"]:
                result["error_code"] = "MODEL_NOT_FOUND"
                result["message"] = f"Model '{self._model}' not found. Available: {models[:5]}"
                return result
        except Exception as e:
            result["error_code"] = "OLLAMA_OFFLINE"
            result["message"] = str(e)[:200]
            return result

        try:
            start = time.perf_counter()
            r = requests.post(f"{self._base_url}/api/generate", json={
                "model": self._model, "prompt": "Reply with only the word OK.",
                "stream": False, "options": {"num_predict": 5},
            }, timeout=(5, 30))
            if r.status_code != 200:
                result["error_code"] = "OLLAMA_HTTP_ERROR"
                result["message"] = f"Inference returned {r.status_code}: {r.text[:200]}"
                return result
            d = r.json()
            resp_text = d.get("response", "").strip()
            result["inference_ok"] = "OK" in resp_text or "ok" in resp_text.lower()
            result["latency_ms"] = int((time.perf_counter() - start) * 1000)
            if result["inference_ok"]:
                result["message"] = "Ollama 推理正常"
            else:
                result["error_code"] = "OLLAMA_INVALID_RESPONSE"
                result["message"] = f"Inference returned unexpected: '{resp_text[:100]}'"
        except requests.Timeout:
            result["error_code"] = "OLLAMA_TIMEOUT"
            result["message"] = "Diagnostic inference timed out (30s)"
        except Exception as e:
            result["error_code"] = "OLLAMA_HTTP_ERROR"
            result["message"] = str(e)[:200]

        return result
