import json, time
import webview

RESULT = {}

def probe(window):
    time.sleep(8)
    try:
        r = window.evaluate_js(
            "(function(){var pg=document.getElementById('page-memory');"
            "if(!pg) return 'NO_PAGE';"
            "var els=[...document.querySelectorAll('#page-memory input.switch')];"
            "return JSON.stringify(els.map(function(el){var r=el.getBoundingClientRect();"
            "var cs=getComputedStyle(el,'::after');"
            "return {c:el.checked,x:Math.round(r.x),y:Math.round(r.y),w:r.width,h:r.height,op:cs.opacity};}));})()"
        )
        RESULT["probe"] = r
    except Exception as e:
        RESULT["probe"] = "ERR " + str(e)
    window.destroy()

w = webview.create_window("probe", "http://127.0.0.1:42001/index.html", width=1100, height=750)
webview.start(func=probe, args=(w,), private_mode=False)
print("PROBE_RESULT=" + json.dumps(RESULT, ensure_ascii=False))