#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import json
import time
import http.client
import requests
from datetime import datetime
from rapidfuzz import fuzz
import sqlite3
from pathlib import Path



#----------------爬取配置-------------------
ANILIST_API = "https://graphql.anilist.co"
JIKAN_API = "https://api.jikan.moe/v4"
BANGUMI_SEARCH_API = "https://api.bgm.tv/search/subject/{keyword}"
BANGUMI_SUBJECT_API = "https://api.bgm.tv/v0/subjects/{id}"

def bangumi_search_subject(keyword: str, limit=10):
    """
    用 Bangumi 搜索动画条目
    """
    if not keyword:
        return []
    time.sleep(0.4)  # 适当限速
    params = {
        "type": 2,      # 2=动画
        "responseGroup": "small",
        "max_results": limit
    }
    url = BANGUMI_SEARCH_API.format(keyword=requests.utils.quote(keyword))
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("list", []) or []

def bangumi_pick_best(anilist_item, candidates):
    """
    用名称相似度选 Bangumi 最佳候选
    """
    a_titles = [
        anilist_item["title"].get("romaji") or "",
        anilist_item["title"].get("english") or "",
        anilist_item["title"].get("native") or "",
    ]
    a_titles_norm = [normalize_title(t) for t in a_titles if t]

    best = None
    best_score = -1

    for c in candidates:
        c_titles = [c.get("name", ""), c.get("name_cn", "")]
        c_titles_norm = [normalize_title(t) for t in c_titles if t]
        if not c_titles_norm:
            continue

        score = 0
        for at in a_titles_norm:
            for ct in c_titles_norm:
                score = max(score, fuzz.ratio(at, ct))

        # 年份辅助
        air_date = c.get("air_date") or ""   # 例如 2026-01-01
        byear = int(air_date[:4]) if len(air_date) >= 4 and air_date[:4].isdigit() else None
        if byear and anilist_item.get("seasonYear") and byear == anilist_item["seasonYear"]:
            score += 5

        if score > best_score:
            best_score = score
            best = c

    return best, best_score

def has_chinese(text: str) -> bool:
    return bool(text and re.search(r"[\u4e00-\u9fff]", text))

def get_current_season():
    m = datetime.now().month
    if m <= 3:
        return "WINTER"
    elif m <= 6:
        return "SPRING"
    elif m <= 9:
        return "SUMMER"
    return "FALL"

def season_cn(season):
    return {"WINTER": "冬季", "SPRING": "春季", "SUMMER": "夏季", "FALL": "秋季"}.get(season, season)

def normalize_title(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    # 去掉常见符号，方便比对
    s = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def unify_season_title(title: str) -> str:
    """
    将中文/日文常见“第X期”统一为 “Season X”
    例如：
    - 葬送のフリーレン 第2期 -> 葬送のフリーレン Season 2
    - 葬送のフリーレン 第二期 -> 葬送のフリーレン Season 2
    """
    if not title:
        return title

    t = title.strip()

    # 先处理阿拉伯数字：第2期 / 第 2 期
    m = re.search(r"^(.*?)[\s　]*第[\s　]*(\d+)[\s　]*期\s*$", t)
    if m:
        base = m.group(1).strip()
        num = int(m.group(2))
        return f"{base} Season {num}"

    # 再处理中文数字：第一期、第二期...第十二期（可按需扩展）
    cn_num_map = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
        "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    }

    m = re.search(r"^(.*?)[\s　]*第[\s　]*([一二三四五六七八九十]{1,3})[\s　]*期\s*$", t)
    if m:
        base = m.group(1).strip()
        cn_num = m.group(2)
        num = cn_num_map.get(cn_num)
        if num:
            return f"{base} Season {num}"

    return title

def anilist_top10_current_season():
    year = datetime.now().year
    season = get_current_season()

    query = """
    query ($season: MediaSeason!, $seasonYear: Int!, $page: Int!, $perPage: Int!) {
      Page(page: $page, perPage: $perPage) {
        media(
          season: $season
          seasonYear: $seasonYear
          type: ANIME
          sort: SCORE_DESC
          isAdult: false
        ) {
          id
          seasonYear
          season
          episodes
          title { romaji native english }
          averageScore
        }
      }
    }
    """
    variables = {"season": season, "seasonYear": year, "page": 1, "perPage": 10}
    r = requests.post(ANILIST_API, json={"query": query, "variables": variables}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if "errors" in j:
        raise RuntimeError(j["errors"])
    return year, season, j["data"]["Page"]["media"]

def jikan_search_anime(query: str, limit=10):
    # Jikan 免费接口有频率限制，适当 sleep
    time.sleep(0.4)
    r = requests.get(f"{JIKAN_API}/anime", params={"q": query, "limit": limit}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("data", [])

def pick_best_jikan_match(anilist_item, candidates):
    """
    用多字段模糊匹配挑最像的条目，减少错配
    """
    a_titles = [
        anilist_item["title"].get("romaji") or "",
        anilist_item["title"].get("english") or "",
        anilist_item["title"].get("native") or "",
    ]
    a_titles_norm = [normalize_title(t) for t in a_titles if t]

    best = None
    best_score = -1

    for c in candidates:
        # Jikan 可用标题集合
        c_titles = [c.get("title") or "", c.get("title_english") or "", c.get("title_japanese") or ""]
        for syn in c.get("titles", []):
            t = syn.get("title")
            if t:
                c_titles.append(t)

        c_titles_norm = [normalize_title(t) for t in c_titles if t]
        if not c_titles_norm:
            continue

        # 取 AniList 各标题 vs Jikan 各标题 的最高相似度
        score = 0
        for at in a_titles_norm:
            for ct in c_titles_norm:
                score = max(score, fuzz.ratio(at, ct))

        # 年份辅助（同年加一点分）
        try:
            aired_from = (c.get("aired") or {}).get("from") or ""
            jikan_year = int(aired_from[:4]) if aired_from[:4].isdigit() else None
        except Exception:
            jikan_year = None

        if jikan_year and anilist_item.get("seasonYear") and jikan_year == anilist_item["seasonYear"]:
            score += 5

        if score > best_score:
            best_score = score
            best = c

    return best, best_score

def get_simplified_chinese_title(anilist_item):
    romaji = anilist_item["title"].get("romaji") or ""
    english = anilist_item["title"].get("english") or ""
    native = anilist_item["title"].get("native") or ""

    # A. AniList 直接有中文就用
    for t in [english, native, romaji]:
        if has_chinese(t):
            return t

    query_name = romaji or english or native
    if not query_name:
        return "未知标题"

    # B. 先走 Jikan（你原有逻辑）
    try:
        candidates = jikan_search_anime(query_name, limit=12)
        best, score = pick_best_jikan_match(anilist_item, candidates)

        if best and score >= 70:
            # titles 中找 Chinese
            for t in best.get("titles", []):
                t_type = (t.get("type") or "").lower()
                title = t.get("title")
                if title and "chinese" in t_type:
                    return title

            # 同义词找中文
            for s in best.get("title_synonyms", []):
                if has_chinese(s):
                    return s
    except Exception:
        pass  # Jikan 挂了就继续下一源

    # C. Bangumi 自动兜底
    try:
        bgm_candidates = bangumi_search_subject(query_name, limit=10)
        bgm_best, bgm_score = bangumi_pick_best(anilist_item, bgm_candidates)
        if bgm_best and bgm_score >= 65:
            name_cn = (bgm_best.get("name_cn") or "").strip()
            if has_chinese(name_cn):
                return name_cn

            # 若搜索返回没中文名，可再查详情（可选）
            sid = bgm_best.get("id")
            if sid:
                time.sleep(0.3)
                rr = requests.get(BANGUMI_SUBJECT_API.format(id=sid), timeout=20)
                if rr.ok:
                    detail = rr.json()
                    name_cn2 = (detail.get("name_cn") or "").strip()
                    if has_chinese(name_cn2):
                        return name_cn2
    except Exception:
        pass

    # D. 最终回退
    return native or romaji or english or "未知标题"



#----------------MP订阅-------------------
MP_URL = 'http://192.168.110.251:3000'
MP_API_KEY = "fa515eb456fe4ae3bbb35ecdc694b826"
PUSHPLUS_TOKEN = 'b8818418079a4c04908b3954bad91f55'

def add_sub(payload: dict):
    # 1. 配置基本信息
    url = MP_URL + "/api/v1/subscribe/"
    api_key = MP_API_KEY

    # 2. 设置请求头 (使用 X-API-KEY 认证)
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    print('正在添加MP订阅...')

    try:
        # 4. 发送 POST 请求
        # json=payload 会自动将字典转换为 JSON 字符串，并设置 Content-Type
        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # 5. 检查 HTTP 状态码 (如 200)
        response.raise_for_status()

        # 6. 解析 JSON 响应
        result_data = response.json()

        # 7. 根据业务逻辑判断成功与否
        if result_data["success"]:
            print("✅ 操作成功!")
            print(f"结果: {payload['name']} ({payload['year']}) 已添加订阅")
            return True
        else:
            print("❌ 操作失败!")
            print(f"错误信息: {result_data}")
            return False

    except requests.exceptions.RequestException as e:
        # 处理网络错误 (连接超时、DNS 错误等)
        print(f"❌ 网络请求异常: {e}")
    except json.JSONDecodeError:
        # 处理返回内容不是有效 JSON 的情况
        print(f"❌ 无法解析响应内容: {response.text}")

def query_site():
    # 1. 配置基本信息
    url = MP_URL + "/api/v1/site/"
    api_key = MP_API_KEY

    # 2. 设置请求头 (使用 X-API-KEY 认证)
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    print('正在查询MP站点信息...')

    try:
        # 4. 发送 POST 请求
        # json=payload 会自动将字典转换为 JSON 字符串，并设置 Content-Type
        response = requests.get(url, headers=headers, timeout=10)

        # 5. 检查 HTTP 状态码 (如 200)
        response.raise_for_status()

        # 6. 解析 JSON 响应
        result_data = response.json()

        print(result_data)

    except requests.exceptions.RequestException as e:
        # 处理网络错误 (连接超时、DNS 错误等)
        print(f"❌ 网络请求异常: {e}")
    except json.JSONDecodeError:
        # 处理返回内容不是有效 JSON 的情况
        print(f"❌ 无法解析响应内容: {response.text}")

def rename_title(original_title: str):
    title = original_title.split('Season')[0]
    season = original_title.split('Season')[-1]
    if title == season:
        return title, 1
    else:
        return title, season

def pushplus(api_token:str, title:str, content:str):
    conn = http.client.HTTPSConnection("www.pushplus.plus")
    payload = json.dumps({
        "token": api_token,
        "title": title,
        "content": content,
    })
    headers = {
        'Content-Type': 'application/json'
    }
    conn.request("POST", "/send", payload, headers)
    res = conn.getresponse()
    data = res.read()
    return data.decode("utf-8")



#----------------查重配置-------------------
DB_FILE = "Anime_records.db"
TABLE_NAME = "Anime_records"

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()

def record_string(content: str) -> bool:
    """
    如果字符串不存在则记录当前时间并返回 True；
    如果已存在则不重复记录并返回 False。
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        try:
            conn.execute(
                f"INSERT INTO {TABLE_NAME} (content, created_at) VALUES (?, ?)",
                (content, now_str),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # UNIQUE(content) 冲突，说明已存在
            return False

def cleanup_older_than_3_months() -> int:
    """
    删除 created_at 早于当前时间减 3 个月的数据。
    使用 SQLite 内置 datetime('now', '-3 months')。
    返回删除条数。
    """
    with get_conn() as conn:
        cur = conn.execute(
            f"""
            DELETE FROM {TABLE_NAME}
            WHERE datetime(created_at) < datetime('now', '-3 months')
            """
        )
        conn.commit()
        return cur.rowcount

def exists(content: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"SELECT 1 FROM {TABLE_NAME} WHERE content = ? LIMIT 1",
            (content,),
        )
        return cur.fetchone() is not None

def list_all():
    with get_conn() as conn:
        cur = conn.execute(
            f"SELECT id, content, created_at FROM {TABLE_NAME} ORDER BY created_at DESC"
        )
        return cur.fetchall()



#----------------运行配置-------------------
def main():
    year, season, top10 = anilist_top10_current_season()
    print(f"{year}年{season_cn(season)} AniList TOP10（中文简体译名优先）")
    print("-" * 72)
    init_db()  # 一定要先调用

    for i, item in enumerate(top10, 1):
        try:
            cn_title = get_simplified_chinese_title(item)
            cn_title = unify_season_title(cn_title)
            score = item.get("averageScore")
            raw = item["title"].get("romaji") or item["title"].get("native") or "N/A"
            print(f"{i:>2}. {cn_title}  |  AniList评分: {score if score is not None else 'N/A'}  |  原名: {raw}")

            re_title, re_season = rename_title(cn_title)
            payload = {
                "name": re_title,
                "year": str(datetime.now().year),
                "type": "电视剧",
                "season": re_season,
                "sites": [5, 3, 25, 28, 31],
                "exclude": "baha",
                "filter_groups": ["中文字幕"],
                "search_imdbid": 0,
            }
            inserted = record_string(cn_title)
            if inserted:
                if add_sub(payload):
                    pushplus(PUSHPLUS_TOKEN, '最新日漫通知', cn_title)
                    time.sleep(2)
                else:
                    time.sleep(10)
                    payload = {
                        "name": re_title,
                        "year": str(datetime.now().year),
                        "type": "电影",
                        "filter_groups": ["中文字幕"],
                        "search_imdbid": 0,
                    }
                    if add_sub(payload):
                        pushplus(PUSHPLUS_TOKEN, '最新日漫电影', cn_title)
                        time.sleep(2)
                    else:
                        pushplus(PUSHPLUS_TOKEN, '日漫订阅失败', cn_title)
                        time.sleep(2)


        except Exception as e:
            print(e)

    # ===== 示例：清理 =====
    deleted = cleanup_older_than_3_months()
    print('\n')
    print(f"[清理完成] 删除 {deleted} 条超过3个月的记录")
    # ===== 查看当前数据 =====
    print("\n当前记录：")
    for row in list_all():
        print(dict(row))

if __name__ == "__main__":
    # query_site()
    main()
