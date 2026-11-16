"""演示页 A6/A8 验收：headless Chromium + CDP 真点击，逐条断言（21 条）。

对应 tests/e2e.md §4 的复验记录。只做「打开页面 → 点 → 断言 DOM」，不截图、不比像素。

用法（环境与 §0 一致）：
    python tools/web_accept.py --make-fake              # 自己造假锚点 trace 再跑（推荐）
    python tools/web_accept.py TR-20261114-XXXX         # 或指定已存在的 trace
    python tools/web_accept.py --make-fake --base http://127.0.0.1:8000

端口不是 8127 用 --base 或 MEDPAL_WEB_BASE 覆盖；浏览器用 CHROME= 指定。
--make-fake 会调 write_trace() 写库，故要和服务同一个 MEDPAL_DB 且能 import medpal_core。

注意：部分断言锁定了页面文案（「结论 /」「锚点不存在」等），改 apps/web/index.html
的文案时要同步改这里——验收就该把用户看到的字锁住。

退出码：全部通过 0，有断言失败 1，用法不对 2。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:8127"
TIMEOUT = 15.0
CHROME = (
    os.environ.get("CHROME")
    or shutil.which("chromium")
    or shutil.which("google-chrome")
    or shutil.which("chrome")
    or "chrome"
)


class Page:
    """一个标签页：导航 + 求值。CDP 只要文本帧，标准库够用。"""

    def __init__(self, chrome: str):
        self.dir = tempfile.mkdtemp(prefix="medpal-web-")
        self.proc = subprocess.Popen(
            [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--remote-debugging-port=0", "--user-data-dir=" + self.dir, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        info = Path(self.dir) / "DevToolsActivePort"
        for _ in range(200):
            if info.exists() and len(info.read_text().split()) >= 2:
                break
            if self.proc.poll() is not None:
                sys.exit("Chromium 启动失败：用 CHROME 环境变量指定可执行文件")
            time.sleep(0.1)
        port, path = info.read_text().split()[:2]
        self.sock = socket.create_connection(("127.0.0.1", int(port)), timeout=TIMEOUT)
        self.buf = b""
        self.seq = 0
        self.session: str | None = None
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.sock.recv(65536)
        self.buf = self.buf.split(b"\r\n\r\n", 1)[1]
        target = self.call("Target.createTarget", url="about:blank")["targetId"]
        self.session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        self.call("Page.enable")
        self.call("Runtime.enable")

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                sys.exit("CDP 连接断开")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> dict:
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else b""
            data = self._read(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if b1 & 0x0F == 0x1:
                return json.loads(data.decode())
            if b1 & 0x0F == 0x8:
                sys.exit("CDP 连接被浏览器关闭")

    def call(self, method: str, **params):
        self.seq += 1
        msg = {"id": self.seq, "method": method, "params": params}
        if self.session:
            msg["sessionId"] = self.session
        payload = json.dumps(msg).encode()
        head = bytearray([0x81])
        if len(payload) < 126:
            head.append(0x80 | len(payload))
        elif len(payload) < 65536:
            head.append(0x80 | 126)
            head += struct.pack("!H", len(payload))
        else:
            head.append(0x80 | 127)
            head += struct.pack("!Q", len(payload))
        mask = secrets.token_bytes(4)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + mask + body)
        while True:
            reply = self.recv()
            if reply.get("id") == self.seq:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def js(self, expr: str):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("页面 JS 抛错: " + r["exceptionDetails"].get("text", "")[:120])
        return r.get("result", {}).get("value")

    def goto(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def wait(self, expr: str) -> None:
        end = time.time() + TIMEOUT
        while time.time() < end:
            try:
                if self.js("Boolean(" + expr + ")"):
                    return
            except RuntimeError:
                pass
            time.sleep(0.1)
        raise RuntimeError("等待超时: " + expr)

    def viewport(self, width: int, height: int) -> None:
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                  deviceScaleFactor=1, mobile=False)

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)
        shutil.rmtree(self.dir, ignore_errors=True)


RESULTS: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    RESULTS.append((name, bool(cond)))
    print(("  ok   " if cond else "  FAIL ") + name)


def run(fake_trace_id: str, base: str) -> None:
    p = Page(CHROME)
    try:
        # A6：默认态渲染
        p.goto(base + "/web/")
        p.wait("document.querySelectorAll('#out .ev-row').length > 0")
        check("默认态：结论卡渲染", p.js("document.body.innerText.includes('结论 /')") is True)
        check("默认态：决策链 6 步", p.js("document.querySelectorAll('#out .steps li').length") == 6)
        check("默认态：溯源完整率 100%", p.js("document.querySelector('#out .pct').textContent") == "100%")
        check("默认态：证据行 8 条", p.js("document.querySelectorAll('#out .ev-row').length") == 8)

        # A6：点证据展开锚点原文
        check("默认态：点开前证据正文收起",
              p.js("document.querySelector('#out .ev-row .ev-body').hidden") is True)
        p.js("document.querySelector('#out .ev-row .ev-btn').click()")
        p.wait("document.querySelector('#out .ev-row .anchor-text')")
        text = p.js("document.querySelector('#out .ev-row .anchor-text').textContent") or ""
        check("默认态：展开后显示锚点原文", len(text.strip()) > 0)
        check("默认态：已核对行不标红",
              p.js("document.querySelector('#out .ev-row').classList.contains('ev-miss')") is False)

        # A6：点决策链步高亮证据
        p.js("document.querySelector('#out .steps li').click()")
        p.wait("document.querySelectorAll('#out .ev-row.hot').length > 0")
        check("默认态：点决策链步高亮对应证据",
              p.js("document.querySelectorAll('#out .ev-row.hot').length") >= 1)

        # A6：假锚点 trace（资产真、锚点假）
        p.goto(base + "/web/?trace=" + fake_trace_id)
        p.wait("document.querySelectorAll('#out .ev-row').length > 0")
        check("假锚点：完整率 0%", p.js("document.querySelector('#out .pct').textContent") == "0%")
        check("假锚点：证据区整块标红",
              p.js("document.querySelector('#out .card.bad') !== null") is True)
        check("假锚点：行内有 ❌ 未核对",
              p.js("document.body.innerText.includes('❌ 未核对')") is True)
        p.js("document.querySelector('#out .ev-row .ev-btn').click()")
        p.wait("document.querySelector('#out .anchor-miss')")
        check("假锚点：展开显示「锚点不存在」",
              "锚点不存在" in (p.js("document.querySelector('#out .anchor-miss').textContent") or ""))

        # A8：三条一键入口
        p.goto(base + "/web/")
        p.wait("document.querySelectorAll('footer .demo-links a').length === 3")
        check("A8：页脚三条 ?demo= 入口",
              p.js("Array.from(document.querySelectorAll('footer .demo-links a'))"
                   ".map(a => a.getAttribute('href'))")
              == ["?demo=default", "?demo=loading", "?demo=refusal"])

        # A8：加载态是固定骨架画面，不发真实请求
        p.goto(base + "/web/?demo=loading")
        p.wait("document.querySelectorAll('#out .skel').length > 0")
        check("A8：加载态是骨架画面", p.js("document.querySelectorAll('#out .skel').length") >= 10)
        check("A8：加载态横幅写明固定画面",
              p.js("document.body.innerText.includes('演示模式：加载态')") is True)
        check("A8：加载态没有真实证据行",
              p.js("document.querySelectorAll('#out .ev-row').length") == 0)

        # A8：拒答态走真实请求
        p.goto(base + "/web/?demo=refusal")
        p.wait("document.querySelector('#out .refusal-box')")
        check("A8：拒答态渲染拒答卡",
              (p.js("document.querySelector('#out .refusal-main').textContent") or "").strip()
              == "这个问题我不能回答。")
        check("A8：拒答态问句是域外问句",
              p.js("document.getElementById('q').value") == "如何办理签证？")

        # A8：窄屏 375
        p.viewport(375, 720)
        p.goto(base + "/web/")
        p.wait("document.querySelectorAll('#out .ev-row').length > 0")
        check("窄屏 375：两栏上下堆叠",
              p.js("(() => { const c = document.querySelectorAll('#out .grid > .col');"
                   " return c.length > 1 && c[1].getBoundingClientRect().top"
                   " >= c[0].getBoundingClientRect().bottom - 2; })()") is True)
        check("窄屏 375：不横向溢出",
              p.js("document.documentElement.scrollWidth <= window.innerWidth + 1") is True)
        p.js("document.querySelector('#out .ev-row .ev-btn').click()")
        p.wait("document.querySelector('#out .ev-row .anchor-text')")
        check("窄屏 375：展开后输入框仍可见可点",
              p.js("(() => { const q = document.getElementById('q'), r = q.getBoundingClientRect();"
                   " if (r.bottom > window.innerHeight || r.top < 0) return false;"
                   " return document.elementFromPoint("
                   "r.left + r.width / 2, r.top + r.height / 2) === q; })()") is True)
    finally:
        p.close()


def make_fake_anchor_trace() -> str:
    """资产真实存在、锚点不存在 —— 前端才会走「锚点不存在（unresolved）」分支。"""
    from medpal_core.storage.db import connect
    from medpal_core.trace.writer import write_trace

    conn = connect()
    try:
        row = conn.execute("SELECT asset_id FROM asset ORDER BY asset_id LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("库里没有资产：先 python -m app.seed，并确认与服务用同一个 MEDPAL_DB")
        fake = str(row["asset_id"]) + "#s99.p99.c99"
        steps = [
            {"i": 1, "op": "retrieve", "in": ["假锚点复验"], "out": {"backend": "bm25", "hits": 1},
             "evidence": [fake], "ref": "EVIDENCE"},
            {"i": 2, "op": "entity_extract", "in": ["假锚点复验"], "out": ["假锚点复验"]},
            {"i": 3, "op": "std_align", "out": {"matched": []}},
            {"i": 4, "op": "kg_query", "out": {"paths": 0}},
            {"i": 5, "op": "conflict_check", "out": {"conflicts": []}},
            {"i": 6, "op": "conclude", "evidence": [fake],
             "out": {"statement": "假锚点复验（仅用于验收演示页标红）", "dept": "", "exams": [],
                     "drugs": [], "evidence_count": 1, "conflicts": []}},
        ]
        out = write_trace(conn, "假锚点复验", steps, agent_version="web_accept")
    finally:
        conn.close()
    return str(out["trace_id"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="演示页 A6/A8 验收（21 条断言）")
    ap.add_argument("trace_id", nargs="?", default="",
                    help="已存在的假锚点 trace；不给就配 --make-fake")
    ap.add_argument("--make-fake", action="store_true", help="自己造一条假锚点 trace 再跑")
    ap.add_argument("--base", default=os.environ.get("MEDPAL_WEB_BASE", DEFAULT_BASE),
                    help="服务地址（默认 %(default)s，也可用 MEDPAL_WEB_BASE）")
    args = ap.parse_args(argv)

    trace_id = args.trace_id
    if args.make_fake:
        try:
            trace_id = make_fake_anchor_trace()
        except Exception as exc:  # noqa: BLE001 - 缺依赖 / 库不一致都要说清
            print(f"造不出假锚点 trace：{exc}（要同一个 MEDPAL_DB，PYTHONPATH 含 packages/core）")
            return 2
        print(f"假锚点 trace: {trace_id}")
    if not trace_id:
        print("用法: python tools/web_accept.py --make-fake  （或传入已存在的 trace_id）")
        return 2

    try:
        run(trace_id, args.base.rstrip("/"))
    except Exception as exc:  # noqa: BLE001 - 浏览器/网络异常也要给出可读原因
        print(f"  FAIL 执行中断: {exc}（确认 {args.base} 上服务已起、页面可访问）")
        return 1
    passed, total = sum(1 for _, ok in RESULTS if ok), len(RESULTS)
    print(f"\n演示页验收: {passed}/{total} 断言通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
