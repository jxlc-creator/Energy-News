# -*- coding: utf-8 -*-
"""
每日储能情报 digest 生成器
读取 feeds.txt → 拉取所有 RSS → 时间窗过滤 → 关键词过滤 → 去重
→ 生成 digest.md（最新一期，链接固定）+ digests/YYYY-MM-DD.md（存档）
无需任何 API key。依赖：feedparser
"""

import datetime as dt
import html
import re
import time
from pathlib import Path

import feedparser

# ---------------- 配置 ----------------

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
WINDOW_HOURS = 26          # 抓取窗口：过去 26 小时（留 2h 缓冲防漏）
MAX_SUMMARY_CHARS = 220    # 摘要截断长度
MAX_ITEMS_PER_GROUP = 60   # 单组条目上限（防某源爆量刷屏）

# 品类关键词（多语种）。标题或摘要命中任意一个即保留。
# 官方源（feeds.txt 中以 ! 开头）不经过此过滤。
KEYWORDS = [
    # --- 户储 / 家用电池 ---
    "home battery", "home energy storage", "residential energy storage",
    "residential storage", "residential ess", "battery storage", "home ess",
    "wall-mounted battery", "stackable battery", "modular battery",
    "ac-coupled", "dc-coupled", "battery retrofit", "sodium-ion",
    "virtual power plant", "vpp", "demand response", "peak shaving",
    "time-of-use", "dynamic tariff", "hems", "energy management",
    "heimspeicher", "stromspeicher", "batteriespeicher", "solarspeicher",
    "photovoltaik-speicher", "thuisbatterij", "batterie domestique",
    "户储", "户用储能", "家庭储能", "家用储能", "家储", "虚拟电厂", "储能",
    # --- 住宅光伏 ---
    "residential solar", "rooftop solar", "home solar", "residential pv",
    "microinverter", "micro inverter", "hybrid inverter", "string inverter",
    "solar installer", "net metering", "net billing", "feed-in tariff",
    "self-consumption", "solar tile", "solar roof", "bipv",
    "photovoltaik", "pv-anlage", "einspeisevergütung", "wechselrichter",
    "eigenverbrauch", "autoconsumo", "autoconsommation", "salderingsregeling",
    "户用光伏", "住宅光伏", "分布式光伏", "屋顶光伏", "微逆", "逆变器",
    # --- 阳台光储 / 插电式 ---
    "balcony solar", "balcony power", "plug-in solar", "plug-and-play solar",
    "plug-in pv", "balcony battery", "balcony storage", "micro storage",
    "plug-in battery", "plug-in microgenerator", "zero export",
    "balkonkraftwerk", "steckersolar", "stecker-solar", "balkonspeicher",
    "mini-pv", "steckerfertige",
    "阳台光储", "阳台光伏", "阳台储能", "插电式光伏", "微储",
    # --- 备电 / 便携储能 PPS ---
    "backup power", "home backup", "backup battery", "power outage",
    "blackout", "grid outage", "emergency power", "off-grid",
    "portable power station", "solar generator", "power station",
    "apagón", "notstrom", "power bank", "lithium-ion battery","便携储能", "户外电源", "备电", "应急电源",
    "停电", "离网", "移动储能",
    # --- 产业链 / 政策 / 玩家动词 ---
    "lfp", "battery cell", "lithium carbonate", "solid-state battery",
    "gigafactory", "cell price", "battery price",
    "subsidy", "rebate", "tax credit", "incentive", "tariff",
    "grid code", "certification", "safety standard", "recall",
    "regulation", "förderung", "verbot", "rückruf", "urteil", "abmahnung",
    "补贴", "关税", "新规", "认证", "召回", "禁令", "判决",
    "v2h", "v2g", "bidirectional charging", "heat pump",
    # --- 监测公司名（品牌名出现即保留）---
    "marstek", "zendure", "growatt", "foxess", "indevolt", "sigenergy",
    "dyness", "hoymiles", "alphaess", "priwatt", "solmate", "goodwe",
    "aferiy", "powerwall", "luna2000", "fusionsolar", "battery-box",
    "sungrow", "pylontech", "deye", "enphase", "sonnen", "solaredge",
    "franklinwh", "victron", "fogstar", "sunsynk", "solis", "ginlong",
    "sofar", "yuma", "resu", "fronius", "jackery", "bluetti", "anker solix",
    "ecoflow", "catl", "hithium", "eve energy", "svolt", "rept", "sunwoda",
    "gotion", "派能", "德业", "固德威", "禾迈", "锦浪", "首航", "沃太",
    "思格", "大秦", "宁德时代", "亿纬", "海辰", "华宝", "德兰明海",
]

TAG_RE = re.compile(r"<[^>]+>")
NORM_RE = re.compile(r"[\W_]+", re.UNICODE)


def strip_html(text: str) -> str:
    return html.unescape(TAG_RE.sub(" ", text or "")).strip()


def norm_title(title: str) -> str:
    """标题归一化，用于跨源去重"""
    return NORM_RE.sub("", (title or "").lower())


def load_feeds(path="feeds.txt"):
    """解析 feeds.txt → [(组名, url, 是否免过滤)]"""
    feeds, group = [], "未分组"
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            continue
        bypass = line.startswith("!")
        url = line[1:].strip() if bypass else line
        feeds.append((group, url, bypass))
    return feeds


def entry_time(entry):
    """取条目发布时间(UTC)；无时间戳返回 None"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return dt.datetime.fromtimestamp(time.mktime(t), dt.timezone.utc)
    return None


def matches_keywords(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in KEYWORDS)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=WINDOW_HOURS)
    date_str = now.strftime("%Y-%m-%d")

    groups: dict[str, list[dict]] = {}
    health_fail: list[str] = []   # 抓取失败的源
    health_empty: list[str] = []  # 窗口内 0 条的源
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    total_raw = 0

    for group, url, bypass in load_feeds():
        try:
            parsed = feedparser.parse(url, agent=UA)
        except Exception as e:  # noqa: BLE001
            health_fail.append(f"{url}  （异常: {e}）")
            continue
        if parsed.get("bozo") and not parsed.get("entries"):
            reason = getattr(parsed, "bozo_exception", "解析失败")
            health_fail.append(f"{url}  （{reason}）")
            continue

        kept = 0
        for entry in parsed.entries:
            total_raw += 1
            ts = entry_time(entry)
            # 无时间戳的条目：仅免过滤官方源保留（政策页常缺时间戳，宁滥勿缺）
            if ts is None and not bypass:
                continue
            if ts is not None and ts < cutoff:
                continue

            title = strip_html(entry.get("title", "")).strip()
            link = (entry.get("link") or "").strip()
            # Google News 代理源：把包装链接还原为原文真实地址
            if "news.google.com" in link:
                _dec = None
                try:
                    from googlenewsdecoder import gnewsdecoder as _dec
                except ImportError:
                    try:
                        from googlenewsdecoder import new_decoderv1 as _dec
                    except ImportError:
                        print(f"[decode] 库未安装，保留原链接: {link[:60]}")
                if _dec:
                    try:
                        r = _dec(link, interval=1)
                        if isinstance(r, dict) and r.get("status"):
                            link = r.get("decoded_url") or link
                        else:
                            print(f"[decode] 解码失败: {r}")
                    except Exception as e:
                        print(f"[decode] 异常: {e}")
            summary = strip_html(entry.get("summary", ""))[:MAX_SUMMARY_CHARS]
            if not title or not link:
                continue

            # 去重（URL + 归一化标题，跨源）
            nt = norm_title(title)
            if link in seen_urls or (nt and nt in seen_titles):
                continue

            # 关键词过滤（免过滤源跳过）
            if not bypass and not matches_keywords(f"{title} {summary}"):
                continue

            seen_urls.add(link)
            if nt:
                seen_titles.add(nt)
            domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", link).split("/")[0])
            groups.setdefault(group, []).append({
                "title": title,
                "link": link,
                "summary": summary,
                "time": ts,
                "domain": domain,
            })
            kept += 1

        if kept == 0 and url not in [h.split("  ")[0] for h in health_fail]:
            health_empty.append(url)

    # 排序 + 截断
    total_kept = 0
    for g in groups.values():
        g.sort(key=lambda x: x["time"] or now, reverse=True)
        del g[MAX_ITEMS_PER_GROUP:]
        total_kept += len(g)

    # ---------------- 生成 digest.md ----------------
    lines = [
        f"# 每日储能情报 · 候选清单 | {date_str}",
        "",
        f"- 生成时间（UTC）：{now.strftime('%Y-%m-%d %H:%M')}",
        f"- 抓取窗口：过去 {WINDOW_HOURS} 小时",
        f"- 原始条目：{total_raw} 条 → 过滤去重后：**{total_kept} 条**",
        "",
        "> 用途：将本文件交给 Claude（energy-storage-intel skill）分类、评级并生成中文简报。",
        "",
    ]

    for group, items in groups.items():
        if not items:
            continue
        lines.append(f"## {group}（{len(items)} 条）")
        lines.append("")
        for it in items:
            tstr = it["time"].strftime("%Y-%m-%d %H:%M UTC") if it["time"] else "（无时间戳）"
            lines.append(f"- **{it['title']}** — {it['domain']} | {tstr}")
            lines.append(f"  {it['link']}")
            if it["summary"]:
                lines.append(f"  > {it['summary']}")
        lines.append("")

    lines.append("## ⚠️ 信源健康")
    lines.append("")
    if health_fail:
        lines.append("**抓取失败（请检查地址是否变更）：**")
        lines.extend(f"- {h}" for h in health_fail)
    else:
        lines.append("- 全部信源抓取成功 ✅")
    if health_empty:
        lines.append("")
        lines.append(f"**窗口内 0 条（正常情况居多，连续多日为 0 才需要检查）：** {len(health_empty)} 个源")
        lines.extend(f"- {h}" for h in health_empty)
    lines.append("")

    out = "\n".join(lines)
    Path("digest.md").write_text(out, encoding="utf-8")
    Path("digests").mkdir(exist_ok=True)
    Path(f"digests/{date_str}.md").write_text(out, encoding="utf-8")
    print(f"digest 生成完毕：{total_kept} 条（原始 {total_raw} 条），失败源 {len(health_fail)} 个")


if __name__ == "__main__":
    main()
