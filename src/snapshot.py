# src/snapshot.py — 取即時全市場快照 + 分類聚合 → data/live.json
#
# 即時資金流（綜合）：以 taiwan_stock_tick_snapshot 的盤中累計欄位計算，非盤後三大法人。
#   每類股：成交值(total_amount)、淨流入(漲家成交額−跌家成交額)、漲/跌家數、均漲跌(額加權)、
#           委買/委賣量(最佳買賣盤)。分類沿用 產業別(互斥) + 產業鏈(多對多)。
#
# 用法（Action 與本機共用）：python src/snapshot.py  → 寫 data/live.json

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fin  # noqa: E402

OUT = fin.ROOT / "data" / "live.json"
CLASSIFY = fin.ROOT / "data" / "classify.json"
TPE = timezone(timedelta(hours=8))


def _classify() -> dict:
    return json.loads(CLASSIFY.read_text(encoding="utf-8"))["map"]


def _acc(d: dict, key: str, amt: float, chg: float, bv: float, sv: float):
    o = d.get(key)
    if not o:
        o = d[key] = {"sector": key, "amt": 0.0, "inflow": 0.0, "wchg": 0.0,
                      "up": 0, "down": 0, "flat": 0, "n": 0, "bv": 0.0, "sv": 0.0}
    o["amt"] += amt
    o["wchg"] += chg * amt
    o["bv"] += bv
    o["sv"] += sv
    o["n"] += 1
    if chg > 0:
        o["up"] += 1
        o["inflow"] += amt
    elif chg < 0:
        o["down"] += 1
        o["inflow"] -= amt
    else:
        o["flat"] += 1


def _finalize(d: dict) -> list:
    out = []
    for o in d.values():
        amt = o["amt"]
        out.append({"sector": o["sector"], "amt_yi": round(amt / 1e8, 2),
                    "inflow_yi": round(o["inflow"] / 1e8, 2),
                    "avg_chg": round(o["wchg"] / amt, 2) if amt else 0.0,
                    "up": o["up"], "down": o["down"], "flat": o["flat"], "n": o["n"],
                    "bv": round(o["bv"]), "sv": round(o["sv"])})
    out.sort(key=lambda x: x["amt_yi"], reverse=True)
    return out


def build_live() -> dict:
    cl = _classify()
    rows = fin.snapshot_all()
    ts = None
    stocks, ex, ch = {}, {}, {}
    mk = {"amt": 0.0, "up": 0, "down": 0, "flat": 0, "n": 0}
    for r in rows:
        code = str(r.get("stock_id") or "")
        if not code:
            continue
        info = cl.get(code)
        if not info:
            continue  # 非個股的 pseudo-row（如 001=加權指數、各類股指數）不計入
        amt = float(r.get("total_amount") or 0)
        c = r.get("change_rate")
        chg = float(c) if c is not None else 0.0
        bv = float(r.get("buy_volume") or 0)
        sv = float(r.get("sell_volume") or 0)
        ts = ts or r.get("date")
        # 個股即時：壓成陣列 [chg, amt(元), close, vol, bv, sv] 省體積
        stocks[code] = [round(chg, 2), round(amt), r.get("close"), r.get("total_volume"), round(bv), round(sv)]
        mk["amt"] += amt
        mk["n"] += 1
        if chg > 0:
            mk["up"] += 1
        elif chg < 0:
            mk["down"] += 1
        else:
            mk["flat"] += 1
        _acc(ex, info["e"], amt, chg, bv, sv)
        for nd in info["c"]:
            _acc(ch, nd, amt, chg, bv, sv)

    cov = sum(1 for code in stocks if cl.get(code) and cl[code]["c"])
    live = {"ts": ts, "generated_at": datetime.now(TPE).isoformat(),
            "stock_cols": ["chg", "amt", "close", "vol", "bv", "sv"],
            "market": {"amt_yi": round(mk["amt"] / 1e8, 1), "up": mk["up"], "down": mk["down"],
                       "flat": mk["flat"], "n": mk["n"]},
            "exchange": _finalize(ex), "chain": _finalize(ch),
            "chain_coverage": {"with_chain": cov, "total": len(stocks)},
            "stocks": stocks}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(live, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return live


if __name__ == "__main__":
    L = build_live()
    m = L["market"]
    print(f"live.json：ts={L['ts']} | 大盤成交 {m['amt_yi']:.0f}億 漲{m['up']}/跌{m['down']}/平{m['flat']} | "
          f"產業別 {len(L['exchange'])} 類、產業鏈 {len(L['chain'])} 類、{m['n']} 檔 | "
          f"{OUT.stat().st_size/1024:.0f} KB")
