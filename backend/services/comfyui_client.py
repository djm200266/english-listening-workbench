"""
ComfyUI API client.

Workflow:
  POST /prompt         → { prompt_id }
  GET  /history/{id}   → { outputs: { "19": { images: [...] } } }
  GET  /view?filename=  → image binary

Handles polling, timeout, and error recovery.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import requests

from config import get_config


class ComfyUIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ComfyUIClient:
    def __init__(self) -> None:
        cfg = get_config().get("comfyui", {})
        self._base = cfg.get("baseUrl", "http://127.0.0.1:8188").rstrip("/")
        self._timeout = int(cfg.get("timeoutSec", 120))
        self._poll_interval = float(cfg.get("pollIntervalSec", 2))
        self._client_id = f"english-workbench-{uuid.uuid4().hex[:8]}"

    def submit_workflow(self, workflow: dict[str, Any]) -> str:
        """Submit a workflow, return prompt_id."""
        url = f"{self._base}/prompt"
        payload = {"prompt": workflow, "client_id": self._client_id}
        try:
            resp = requests.post(url, json=payload, timeout=30)
        except requests.ConnectionError:
            raise ComfyUIError(
                f"无法连接到 ComfyUI ({self._base})。请确认 ComfyUI 已启动。"
            )
        except requests.Timeout:
            raise ComfyUIError("ComfyUI /prompt 请求超时。")

        if resp.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI /prompt 返回错误 (HTTP {resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        prompt_id = data.get("prompt_id", "")
        if not prompt_id:
            raise ComfyUIError("ComfyUI 未返回 prompt_id。")
        return prompt_id

    def wait_for_result(self, prompt_id: str) -> dict[str, Any]:
        """
        Poll /history/{prompt_id} until the job completes or times out.

        Returns the history entry for this prompt_id.
        """
        url = f"{self._base}/history/{prompt_id}"
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > self._timeout:
                raise ComfyUIError(
                    f"ComfyUI 图片生成超时（{self._timeout}秒）。prompt_id={prompt_id}"
                )

            try:
                resp = requests.get(url, timeout=10)
            except requests.ConnectionError:
                time.sleep(self._poll_interval)
                continue

            if resp.status_code != 200:
                time.sleep(self._poll_interval)
                continue

            data = resp.json()
            if prompt_id in data:
                return data[prompt_id]

            time.sleep(self._poll_interval)

    def get_image_info(self, history_entry: dict[str, Any]) -> list[dict[str, str]]:
        """
        Extract image metadata from a completed history entry.

        Returns list of { "filename": str, "subfolder": str, "type": str }.
        """
        outputs = history_entry.get("outputs", {})
        # Node 19 is SaveImage — find it
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                return images
        raise ComfyUIError("ComfyUI history 中未找到输出图片。")

    def download_image(self, filename: str, subfolder: str = "", output_path: str = "") -> bytes:
        """
        Download a generated image from ComfyUI.

        Returns raw image bytes. If output_path is given, also saves to disk.
        """
        params = {"filename": filename, "subfolder": subfolder, "type": "output"}
        url = f"{self._base}/view"
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise ComfyUIError(
                f"ComfyUI 图片下载失败 (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        if output_path:
            import os
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.content)
        return resp.content

    def health_check(self) -> dict[str, Any]:
        """Quick connectivity check — returns structured result."""
        try:
            resp = requests.get(f"{self._base}/system_stats", timeout=5,
                              proxies={"http": None, "https": None})
            return {"available": resp.status_code == 200, "status_code": resp.status_code, "error": None}
        except requests.ConnectionError as e:
            return {"available": False, "status_code": None, "error": f"ConnectionError: {e}"}
        except requests.Timeout as e:
            return {"available": False, "status_code": None, "error": f"Timeout: {e}"}
        except Exception as e:
            return {"available": False, "status_code": None, "error": f"{type(e).__name__}: {e}"}
