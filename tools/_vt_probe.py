import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import winhance

t = winhance.list_tunes()
with open(r"C:\Users\陈耿峰\AppData\Local\Temp\vt_out.json", "w", encoding="utf-8") as f:
    json.dump({
        "total": len(t),
        "first": t[0],
        "selection_first": next((x for x in t if x["input_type"] == "selection"), None),
        "no_hint": [x["id"] for x in t if not x.get("value_hint")],
    }, f, ensure_ascii=False, indent=2)
print("total", len(t))
