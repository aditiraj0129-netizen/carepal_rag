import re, sys, json
from playwright.sync_api import sync_playwright, expect

import os
KEY = os.environ["ADMIN_API_KEY"]  # the same key the backend was started with
SHOTS = sys.argv[2]; MODE = sys.argv[1]  # desktop | mobile
URL = "http://127.0.0.1:5173/"
problems = []

def run(p):
    b = p.chromium.launch()
    if MODE == "mobile":
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    else:
        ctx = b.new_context(viewport={"width": 1366, "height": 820})
    pg = ctx.new_page()
    pg.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    pg.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url} {r.failure}") if "fonts.g" not in r.url else None)
    def shot(n):
        pg.wait_for_timeout(450)  # let entrance animations finish
        pg.screenshot(path=f"{SHOTS}/{MODE}-{n}.png")

    pg.goto(URL); pg.wait_for_selector("h1")
    globals()["PG"]=pg
    # horizontal overflow check
    ov = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    print("overflow-x welcome:", ov); 
    if ov > 0: problems.append(f"horizontal overflow {ov}px on welcome")
    shot("01-welcome")

    # --- grounded answer through suggested question
    pg.get_by_role("button", name="What is the refund policy?").click()
    pg.wait_for_selector("text=non-refundable", timeout=20000)
    pg.wait_for_selector("text=Was this helpful?", timeout=20000)
    cite_btn = pg.locator("button[aria-label^='Source ']").first
    print("inline citation buttons:", pg.locator("button[aria-label^='Source ']").count())
    cite_btn.click()
    pg.wait_for_selector("[role=dialog][aria-label='Source preview']")
    panel = pg.locator("[role=dialog][aria-label='Source preview']")
    txt = panel.inner_text(); print("source panel has url:", "https://www.thecarepal.com/refund" in txt)
    assert "https://www.thecarepal.com/refund" in txt
    href = panel.get_by_role("link", name=re.compile("Open page")).get_attribute("href"); print("open link:", href)
    assert href == "https://www.thecarepal.com/refund"
    shot("02-answer-source-preview")
    panel.get_by_role("button", name="Close").click()
    pg.get_by_role("button", name="Helpful", exact=True).click()
    pg.wait_for_selector("text=Thanks for your feedback")
    shot("03-feedback")

    # --- abstention -> handoff -> escalation form
    pg.locator("#composer").fill("How much does elderly care cost?"); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=Want a person to look at this?", timeout=20000)
    shot("04-abstain-handoff")
    pg.get_by_role("button", name="Talk to a person").last.click()
    dlg = pg.locator("[role=dialog][aria-modal=true]"); dlg.wait_for()
    shot("05-escalation-form")
    dlg.get_by_role("button", name="Save my request").click()
    for msg in ["Please enter your name", "Enter a valid 10-digit", "Please tick the box"]:
        dlg.get_by_text(re.compile(msg)).first.wait_for()
    dlg.get_by_label("Your name").fill("Asha Rao")
    dlg.get_by_label("Mobile number").fill("12345")
    dlg.get_by_role("checkbox").check()
    dlg.get_by_role("button", name="Save my request").click()
    dlg.get_by_text(re.compile("Enter a valid 10-digit")).first.wait_for()
    shot("06-escalation-validation")
    dlg.get_by_label("Mobile number").fill("98765 43211")
    dlg.get_by_role("button", name="Save my request").click()
    rid = dlg.get_by_test_id("request-id"); rid.wait_for(timeout=10000)
    print("request id:", rid.inner_text()); assert re.match(r"SR-\d{8}-[A-Z0-9]{6}", rid.inner_text())
    print("confirmation:", dlg.inner_text().split("What happens next")[1][:200].replace("\n"," "))
    shot("07-escalation-done")
    dlg.get_by_role("button", name="Done").click()

    # --- emergency
    pg.locator("#composer").fill("my father is not breathing and has chest pain"); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=If this is an emergency, call now", timeout=20000)
    tel = pg.locator("a[href^='tel:']"); print("tel links:", tel.all_inner_texts())
    shot("08-emergency")

    # --- Hinglish via UI language + question
    pg.get_by_role("button", name="Hinglish", exact=True).first.click()
    pg.get_by_role("button", name="Nayi chat").first.click()
    pg.wait_for_selector("text=Aaj hum aapki family")
    shot("09-hinglish-welcome")
    pg.get_by_role("button", name=re.compile("Mere papa ko dementia")).click()
    pg.wait_for_selector("[role=log] >> text=dementia", timeout=20000); pg.wait_for_selector("text=Kya ye jawab kaam ka tha?", timeout=20000)
    shot("10-hinglish-answer")
    # Hindi
    pg.get_by_role("button", name="हिन्दी", exact=True).first.click()
    pg.get_by_role("button", name="नई चैट").first.click()
    pg.wait_for_selector("text=आज हम आपके परिवार")
    pg.locator("#composer").fill("रिफंड पॉलिसी क्या है?"); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=क्या यह उत्तर उपयोगी था?", timeout=20000)
    shot("11-hindi-answer")
    print("hindi answer:", pg.locator("[role=log] p").last.inner_text()[:160].replace("\n"," "))

    # --- history persistence
    print("stored titles:", pg.evaluate("JSON.parse(localStorage.getItem('carepal-assist:conversations:v1')||'[]').map(c=>c.title)"))
    pg.reload(); pg.wait_for_selector("h1")
    if MODE == "mobile": pg.get_by_role("button", name=re.compile("^(History|इतिहास)$")).first.click()
    items = pg.locator("nav[aria-label] li").count(); print("history items after reload:", items); assert items >= 3
    shot("12-history")
    pg.locator("nav[aria-label] li button:visible").first.click()
    pg.wait_for_selector("[role=log]")
    shot("13-history-open")

    # --- admin
    pg.goto(URL + "#/admin"); pg.wait_for_selector("text=Admin sign-in")
    pg.get_by_label("Admin key").fill("wrong-key"); pg.get_by_role("button", name="Sign in").click()
    pg.wait_for_selector("text=That admin key was not accepted")
    shot("14-admin-login-error")
    pg.get_by_label("Admin key").fill(KEY); pg.get_by_role("button", name="Sign in").click()
    pg.wait_for_selector("text=Operations dashboard"); pg.wait_for_selector("text=Knowledge gaps")
    kp = {k: pg.get_by_test_id(f"kpi-{k}").inner_text() for k in ["Conversations","Answered","Unanswered","Escalations"]}
    print("KPIs:", kp)
    ov = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"); print("overflow-x admin:", ov)
    if ov > 0: problems.append(f"horizontal overflow {ov}px on admin")
    pg.wait_for_timeout(450); pg.screenshot(path=f"{SHOTS}/{MODE}-15-admin.png", full_page=True)
    pg.get_by_role("button", name="Show numbers").click()
    pg.get_by_role("button", name="Run evaluation (dev split)").click()
    pg.wait_for_selector("text=answerable questions", timeout=60000)
    pg.screenshot(path=f"{SHOTS}/{MODE}-16-admin-eval.png", full_page=True)
    pg.get_by_role("button", name="Run incremental ingest").click()
    pg.wait_for_selector("text=Ingestion ok", timeout=60000); print("ingest msg:", pg.locator("[role=status]").last.inner_text())
    pg.get_by_role("button", name="Sign out").click(); pg.wait_for_selector("text=Admin sign-in")
    b.close()

try:
    with sync_playwright() as p: run(p)
except Exception as e:
    import traceback; traceback.print_exc(limit=-3); print("FAILED:", str(e)[:600])
print("PROBLEMS:", json.dumps(problems, indent=1) if problems else "none")
