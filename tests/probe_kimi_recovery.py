#!/usr/bin/env python3
"""Check native Kimi context delivery against a local stub model, without credentials."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def install_plugin(kimi, env, workspace):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/api/v1/plugins"
    with tempfile.TemporaryFile() as log:
        # This disposable, loopback-only test server contains no credentials.
        process = subprocess.Popen([kimi, "web", "--no-open", "--port", str(port),
                                    "--dangerous-bypass-auth"], cwd=workspace,
                                   env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(url, timeout=1):
                        break
                except (OSError, urllib.error.URLError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise AssertionError(log.read().decode(errors="replace")[-3000:])
                    time.sleep(0.1)
            request = urllib.request.Request(url, method="POST",
                data=json.dumps({"source": str(ROOT / "plugins/task-state-with-files")}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)
            assert result.get("code") == 0, result
            assert result["data"]["state"] == "ok", result
            assert result["data"]["hookCount"] == 1, result
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    kimi = shutil.which("kimi")
    if not kimi:
        raise SystemExit("Install native Kimi Code and put kimi on PATH first.")
    requests = []

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [({"role": "assistant", "content": "PROBE_OK"}, None), ({}, "stop")]:
                chunk = {"id": "probe", "object": "chat.completion.chunk", "created": 1,
                         "model": "probe", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as server, tempfile.TemporaryDirectory() as temp:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            home = Path(temp)
            kimi_home = home / "custom kimi home"
            kimi_home.mkdir()
            workspace = home / "project"
            (workspace / "work").mkdir(parents=True)
            marker = "RECOVERY-" + uuid4().hex
            (workspace / "work/task-state.md").write_text("## Next action\n" + marker + "\n")
            (kimi_home / "config.toml").write_text(f'''default_model = "probe"
builtin_product_skills = false
[providers.probe]
type = "openai"
base_url = "http://127.0.0.1:{server.server_port}/v1"
api_key = "local-probe-only"
[models.probe]
provider = "probe"
model = "probe"
max_context_size = 262144
capabilities = []
''')
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("KIMI_", "TASK_STATE_"))}
            env.update(KIMI_CODE_HOME=str(kimi_home), KIMI_DISABLE_TELEMETRY="1")
            install = subprocess.run([sys.executable, str(ROOT / "scripts/install_user.py"),
                                      "install", "--hosts", "kimi", "--home", str(home)],
                                     env=env, capture_output=True, text=True, timeout=20)
            assert install.returncode == 0, install.stderr
            result = subprocess.run([kimi, "--model", "probe", "--output-format", "stream-json",
                                     "--prompt", "Reply OK without using any tools."],
                                    cwd=workspace, env=env, capture_output=True, text=True, timeout=50)
            assert result.returncode == 0, result.stderr[-3000:]
            assert requests, "Kimi never reached the local model endpoint."
            assert marker in json.dumps(requests[0]), "Task state did not reach the actual model request."
            assert "PROBE_OK" in result.stdout, "Kimi did not finish the probe response."
            print("PASS: installed UserPromptSubmit hook reached native Kimi's model request.")
            uninstall = subprocess.run([sys.executable, str(ROOT / "scripts/install_user.py"),
                                        "uninstall", "--hosts", "kimi", "--home", str(home)],
                                       env=env, capture_output=True, text=True, timeout=20)
            assert uninstall.returncode == 0, uninstall.stderr
            install_plugin(kimi, env, workspace)
            requests.clear()
            marker = "PLUGIN-RECOVERY-" + uuid4().hex
            (workspace / "work/task-state.md").write_text("## Next action\n" + marker + "\n")
            result = subprocess.run([kimi, "--model", "probe", "--output-format", "stream-json",
                                     "--prompt", "Reply OK without using any tools."],
                                    cwd=workspace, env=env, capture_output=True, text=True, timeout=50)
            assert result.returncode == 0, result.stderr[-3000:]
            assert requests and marker in json.dumps(requests[0]), "Native plugin recovery did not reach the model request."
            print("PASS: native plugin discovery and relative hook command reached Kimi's model request.")
            print("Model endpoint: local stub; no live model reasoning or compaction claim.")
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
