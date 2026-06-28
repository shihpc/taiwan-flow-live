# src/snapshot.py — 取即時全市場快照 + 分類聚合 + 指數貢獻點數 → data/live.json
#
# 即時資金流（綜合，皆由 tick_snapshot 盤中欄位算，非盤後三大法人）：
#   成交值(total_amount)、淨流入(漲家額−跌家額)、均漲跌(額加權)、漲跌家數、委買/委賣量。
#
# 指數貢獻點數（個股對大盤漲跌點的影響，再彙整成類股）：
#   pts_i = ΔIndex × (Δprice_i × 發行股數_i) / Σ_同市場(Δprice_j × 股數_j)
#   → Σpts = 指數實際漲跌點（自洽）。TSE=001 加權指數、OTC=101 櫃買指數；
#   構成股＝該市場(twse/tpex)普通股（排除 ETF/00 開頭）；類股貢獻＝成分股 pts 加總。
#
# 用法：python src/snapshot.py  → 寫 data/live.json

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
IDX = {"twse": "001", "tpex": "101"}  # snapshot 指數 pseudo-code


def _classify() -> dict:
    return json.loads(CLASSIFY.read_text(encoding="utf-8"))["map"]


def _acc(d: dict, key: str, amt, chg, bv, sv, pts, mkt):
    o = d.get(key)
    if not o:
        o = d[key] = {"sector": key, "amt": 0.0, "inflow": 0.0, "wchg": 0.0, "up": 0, "down": 0,
                      "flat": 0, "n": 0, "bv": 0.0, "sv": 0.0, "pts_tse": 0.0, "pts_otc": 0.0}
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
    if mkt == "twse":
        o["pts_tse"] += pts
    elif mkt == "tpex":
        o["pts_otc"] += pts


def _finalize(d: dict) -> list:
    out = []
    for o in d.values():
        amt = o["amt"]
        out.append({"sector": o["sector"], "amt_yi": round(amt / 1e8, 2),
                    "inflow_yi": round(o["inflow"] / 1e8, 2),
                    "avg_chg": round(o["wchg"] / amt, 2) if amt else 0.0,
                    "up": o["up"], "down": o["down"], "flat": o["flat"], "n": o["n"],
                    "bv": round(o["bv"]), "sv": round(o["sv"]),
                    "pts_tse": round(o["pts_tse"], 2), "pts_otc": round(o["pts_otc"], 2)})
    out.sort(key=lambda x: x["amt_yi"], reverse=True)
    return out


def _idx(rowmap: dict, code: str) -> dict:
    r = rowmap.get(code) or {}
    return {"val": r.get("close"), "chgP": r.get("change_price"), "chg": r.get("change_rate"),
            "vol": r.get("total_volume"), "amt_yi": round(float(r.get("total_amount") or 0) / 1e8, 1)}


def build_live() -> dict:
    cl = _classify()
    rows = fin.snapshot_all()
    ts = None
    idxrow = {}
    items = []                       # 逐檔暫存
    sum_mc = {"twse": 0.0, "tpex": 0.0}   # Σ(Δ價×股數)，指數構成股
    for r in rows:
        code = str(r.get("stock_id") or "")
        if not code:
            continue
        if code in ("001", "101"):
            idxrow[code] = r
            continue
        info = cl.get(code)
        if not info:
            continue                 # 非個股 pseudo-row
        amt = float(r.get("total_amount") or 0)
        c = r.get("change_rate")
        chg = float(c) if c is not None else 0.0
        dv = r.get("change_price")
        dp = float(dv) if dv is not None else 0.0
        bv = float(r.get("buy_volume") or 0)
        sv = float(r.get("sell_volume") or 0)
        ts = ts or r.get("date")
        sh = float(info.get("sh") or 0)
        mkt = info.get("t") or ""
        etf = code.startswith("00")
        items.append((code, info, amt, chg, bv, sv, dp, sh, etf, mkt, r.get("close"), r.get("total_volume")))
        if sh and not etf and mkt in sum_mc:
            sum_mc[mkt] += dp * sh

    dI = {"twse": float((idxrow.get("001") or {}).get("change_price") or 0),
          "tpex": float((idxrow.get("101") or {}).get("change_price") or 0)}

    stocks, ex, ch = {}, {}, {}
    mk = {"amt": 0.0, "up": 0, "down": 0, "flat": 0, "n": 0}
    for code, info, amt, chg, bv, sv, dp, sh, etf, mkt, close, vol in items:
        pts = 0.0
        if sh and not etf and mkt in sum_mc and sum_mc[mkt]:
            pts = dI[mkt] * (dp * sh) / sum_mc[mkt]
        stocks[code] = [round(chg, 2), round(amt), close, vol, round(bv), round(sv), round(pts, 3)]
        mk["amt"] += amt
        mk["n"] += 1
        if chg > 0:
            mk["up"] += 1
        elif chg < 0:
            mk["down"] += 1
        else:
            mk["flat"] += 1
        _acc(ex, info["e"], amt, chg, bv, sv, pts, mkt)
        for nd in info["c"]:
            _acc(ch, nd, amt, chg, bv, sv, pts, mkt)

    cov = sum(1 for code in stocks if cl.get(code) and cl[code]["c"])
    live = {"ts": ts, "generated_at": datetime.now(TPE).isoformat(),
            "stock_cols": ["chg", "amt", "close", "vol", "bv", "sv", "pts"],
            "index": {"tse": _idx(idxrow, "001"), "otc": _idx(idxrow, "101")},
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
    m, ix = L["market"], L["index"]
    t, o = ix["tse"], ix["otc"]
    print(f"live.json：ts={L['ts']} | 大盤成交 {m['amt_yi']:.0f}億 漲{m['up']}/跌{m['down']}")
    print(f"  TSE加權 {t['val']} ({t['chgP']:+}, {t['chg']}%)  量{t['amt_yi']:.0f}億 | "
          f"OTC櫃買 {o['val']} ({o['chgP']:+}, {o['chg']}%) 量{o['amt_yi']:.0f}億")
    # 驗證：Σ類股貢獻點 應 ≈ 指數漲跌點
    st = sum(s["pts_tse"] for s in L["exchange"])
    so = sum(s["pts_otc"] for s in L["exchange"])
    print(f"  Σ產業別貢獻點 TSE={st:.1f}(應≈{t['chgP']}) OTC={so:.1f}(應≈{o['chgP']})")
