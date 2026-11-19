"""Error-state checks: network failure mid-chat, retry, server-down banner, stop button, 429, admin 503."""
import sys
from playwright.sync_api import sync_playwright

SHOTS = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.goto("http://127.0.0.1:5173/"); pg.wait_for_selector("h1")

    # 1) network failure on chat -> inline error + Try again; retry succeeds once the route is restored
    pg.route("**/api/chat/stream", lambda r: r.abort())
    pg.get_by_role("button", name="What is the refund policy?").click()
    pg.wait_for_selector("text=Can't reach the CarePal Assist server")
    pg.wait_for_timeout(450); pg.screenshot(path=f"{SHOTS}/err-1-network.png")
    pg.unroute("**/api/chat/stream")
    pg.get_by_role("button", name="Try again").click()
    pg.wait_for_selector("text=non-refundable", timeout=20000); print("retry after network error: OK")

    # 2) 429 from the API is shown as the server's message
    pg.route("**/api/chat/stream", lambda r: r.fulfill(status=429, content_type="application/json",
             body='{"error":{"code":"http_error","message":"Too many requests; please slow down.","request_id":"x"}}'))
    pg.locator("#composer").fill("hello again"); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=Too many requests"); print("429 shown: OK"); pg.unroute("**/api/chat/stream")

    # 3) stop button aborts a slow stream
    pg.route("**/api/chat/stream", lambda route: None)  # request hangs, like a stalled server
    pg.locator("#composer").fill("a slow question"); pg.keyboard.press("Enter")
    pg.get_by_role("button", name="Stop").click(); pg.wait_for_selector("text=Stopped."); print("stop: OK"); pg.unroute("**/api/chat/stream")

    # 4) server down on page load -> banner with retry
    pg.route("**/api/health", lambda r: r.abort()); pg.reload()
    pg.get_by_role("alert").filter(has_text="Can't reach the server").wait_for(); pg.wait_for_timeout(450); pg.screenshot(path=f"{SHOTS}/err-2-server-down.png"); print("server-down banner: OK")
    pg.unroute("**/api/health")

    # 5) index not ready -> composer disabled + banner
    pg.route("**/api/health", lambda r: r.fulfill(status=200, content_type="application/json", body='{"status":"degraded","version":"x","index_ready":false,"index_error":"no index","chunks":0,"embedding_model":null,"embedding_semantic":null,"embedding_multilingual":null,"generator":"extractive","retrieval_mode":"hybrid","rrf_k":60,"tracing_enabled":false}'))
    pg.reload(); pg.get_by_role("alert").filter(has_text="knowledge base isn't loaded").wait_for()
    assert pg.get_by_role("button", name="Send").is_disabled(); print("index-not-ready state: OK")
    b.close()
