#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import logging
import sqlite3
import http.client
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================
# 配置
# =========================
CONFIG = {
    "api_key": "a084c4dfbcd2cd835816b2f0a30c1686",   # 建议使用环境变量
    "language": "en-US",                        # zh-CN / en-US
    "time_window": "week",                      # day / week
    "days": 7,                                  # 最近N天（7 或 30）
    "top_n": 3,                                # 最近10条
    "pages": 3,                                 # trending抓几页
    "rate_per_sec": 2.0,                        # 每秒最多请求数
    "timeout": 15,                              # 请求超时
    "max_retries": 5,                           # 重试次数

    "db_file": "./cache/tv_cache.db",           # sqlite数据库
    "cache_ttl_days": 14,                       # 缓存有效期
    "cleanup_months": 3,                        # 删除超过3个月的数据

    "mp_url": 'http://192.168.110.251:3000',
    "mp_api_key": "fa515eb456fe4ae3bbb35ecdc694b826",
    "pushplus_token": 'b8818418079a4c04908b3954bad91f55',
    "db_name": "tmdb_series.db",
    "table_name": "tmdb_series",

    "log_level": "INFO"
}
# =========================

BASE_URL = "https://api.themoviedb.org/3"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_dir(path: str):
    if path:
        os.makedirs(path, exist_ok=True)


def parse_date_yyyy_mm_dd(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.min_interval = 1.0 / max(rate_per_sec, 0.0001)
        self.last_ts = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_ts = time.time()


class TMDBClient:
    def __init__(self, api_key: str, language: str, timeout: int, rate_per_sec: float, max_retries: int):
        self.api_key = api_key
        self.language = language
        self.timeout = timeout
        self.rate_limiter = RateLimiter(rate_per_sec)

        self.session = requests.Session()
        retry = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        params.update({
            "api_key": self.api_key,
            "language": self.language
        })
        url = f"{BASE_URL}{path}"

        self.rate_limiter.wait()
        r = self.session.get(url, params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise requests.HTTPError(f"HTTP {r.status_code}: {url} | {r.text[:200]}")
        return r.json()

    def trending_tv(self, time_window: str, page: int) -> Dict[str, Any]:
        return self._get(f"/trending/tv/{time_window}", {"page": page})

    def tv_detail(self, tv_id: int) -> Dict[str, Any]:
        return self._get(f"/tv/{tv_id}")


class TVDetailDB:
    def __init__(self, db_file: str, ttl_days: int, cleanup_months: int = 3):
        self.db_file = db_file
        self.ttl = timedelta(days=ttl_days)
        self.cleanup_months = cleanup_months

        ensure_dir(os.path.dirname(db_file))
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row

        self._init_db()
        self.cleanup_old_data()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tv_details (
                tv_id INTEGER PRIMARY KEY,
                name TEXT,
                first_air_date TEXT,
                status TEXT,
                popularity REAL,
                vote_average REAL,
                vote_count INTEGER,
                original_language TEXT,
                fetched_at TEXT NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tv_details_fetched_at
            ON tv_details(fetched_at)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tv_details_status
            ON tv_details(status)
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tv_details_first_air_date
            ON tv_details(first_air_date)
        """)

        self.conn.commit()

    def cleanup_old_data(self):
        cutoff = utc_now() - timedelta(days=30 * self.cleanup_months)
        cur = self.conn.execute(
            "DELETE FROM tv_details WHERE fetched_at < ?",
            (cutoff.isoformat(),)
        )
        self.conn.commit()
        logging.info("已清理超过 %s 个月的缓存数据，共 %s 条", self.cleanup_months, cur.rowcount)

    def get_cached(self, tv_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("""
            SELECT tv_id, name, first_air_date, status, popularity,
                   vote_average, vote_count, original_language, fetched_at
            FROM tv_details
            WHERE tv_id = ?
        """, (tv_id,))
        row = cur.fetchone()
        if not row:
            return None

        try:
            fetched_at = datetime.fromisoformat(row["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        except Exception:
            return None

        if utc_now() - fetched_at > self.ttl:
            return None

        return {
            "id": row["tv_id"],
            "name": row["name"],
            "first_air_date": row["first_air_date"],
            "status": row["status"],
            "popularity": row["popularity"],
            "vote_average": row["vote_average"],
            "vote_count": row["vote_count"],
            "original_language": row["original_language"],
        }

    def upsert_many(self, items: List[Dict[str, Any]]):
        if not items:
            return

        now_str = utc_now().isoformat()
        rows = []
        for data in items:
            rows.append((
                data.get("id"),
                data.get("name"),
                data.get("first_air_date"),
                data.get("status"),
                data.get("popularity"),
                data.get("vote_average"),
                data.get("vote_count"),
                data.get("original_language"),
                now_str,
            ))

        self.conn.executemany("""
            INSERT INTO tv_details (
                tv_id, name, first_air_date, status, popularity,
                vote_average, vote_count, original_language, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tv_id) DO UPDATE SET
                name = excluded.name,
                first_air_date = excluded.first_air_date,
                status = excluded.status,
                popularity = excluded.popularity,
                vote_average = excluded.vote_average,
                vote_count = excluded.vote_count,
                original_language = excluded.original_language,
                fetched_at = excluded.fetched_at
        """, rows)
        self.conn.commit()

    def query_filtered_by_ids(self, tv_ids: List[int], days: int) -> List[sqlite3.Row]:
        if not tv_ids:
            return []

        cutoff_date = (utc_now() - timedelta(days=days)).strftime("%Y-%m-%d")
        placeholders = ",".join(["?"] * len(tv_ids))
        sql = f"""
            SELECT tv_id, name, first_air_date, status, popularity,
                   vote_average, vote_count, original_language, fetched_at
            FROM tv_details
            WHERE tv_id IN ({placeholders})
              AND status = ?
              AND first_air_date IS NOT NULL
              AND first_air_date >= ?
        """
        params = tv_ids + ["Returning Series", cutoff_date]
        cur = self.conn.execute(sql, params)
        return cur.fetchall()

    def close(self):
        if self.conn:
            self.conn.close()


class MP_ADN_SQ:
    def __init__(self, mp_url: str, mp_api_key: str, pushplus_token: str, db_file: str, table_name: str):
        self.mp_url = mp_url
        self.mp_api_key = mp_api_key
        self.pushplus_token = pushplus_token
        self.db_file = db_file
        self.table_name = table_name

    def add_sub(self, payload: dict):
        # 1. 配置基本信息
        url = self.mp_url + "/api/v1/subscribe/"
        api_key = self.mp_api_key

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

    def query_site(self):
        # 1. 配置基本信息
        url = self.mp_url + "/api/v1/site/"
        api_key = self.mp_api_key

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

    def pushplus(self, title: str, content: str):
        conn = http.client.HTTPSConnection("www.pushplus.plus")
        payload = json.dumps({
            "token": self.pushplus_token,
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

    def get_conn(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_conn() as conn:
            conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """)
            conn.commit()

    def record_string(self, content: str) -> bool:
        """
        如果字符串不存在则记录当前时间并返回 True；
        如果已存在则不重复记录并返回 False。
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            try:
                conn.execute(
                    f"INSERT INTO {self.table_name} (content, created_at) VALUES (?, ?)",
                    (content, now_str),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # UNIQUE(content) 冲突，说明已存在
                return False

    def cleanup_older_than_3_months(self) -> int:
        """
        删除 created_at 早于当前时间减 3 个月的数据。
        使用 SQLite 内置 datetime('now', '-3 months')。
        返回删除条数。
        """
        with self.get_conn() as conn:
            cur = conn.execute(
                f"""
                DELETE FROM {self.table_name}
                WHERE datetime(created_at) < datetime('now', '-3 months')
                """
            )
            conn.commit()
            return cur.rowcount

    def exists(self, content: str) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute(
                f"SELECT 1 FROM {self.table_name} WHERE content = ? LIMIT 1",
                (content,),
            )
            return cur.fetchone() is not None

    def list_all(self):
        with self.get_conn() as conn:
            cur = conn.execute(
                f"SELECT id, content, created_at FROM {self.table_name} ORDER BY created_at DESC"
            )
            return cur.fetchall()



def print_rows(title: str, rows: List[Dict[str, Any]]):
    print(f"\n{'=' * 20} {title} {'=' * 20}")
    print(f"数量: {len(rows)}")
    if not rows:
        print("无数据")
        return

    for idx, row in enumerate(rows, 1):
        print(
            f"{idx:02d}. "
            f"id={row.get('id')} | "
            f"name={row.get('name')} | "
            f"first_air_date={row.get('first_air_date')} | "
            f"status={row.get('status')} | "
            f"popularity={row.get('popularity')} | "
            f"vote_average={row.get('vote_average')} | "
            f"vote_count={row.get('vote_count')} | "
            f"lang={row.get('original_language')}"
        )


def main():
    if not CONFIG["api_key"]:
        raise SystemExit("请先设置环境变量 TMDB_API_KEY，或在 CONFIG['api_key'] 中填写。")

    logging.basicConfig(
        level=getattr(logging, CONFIG["log_level"]),
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    client = TMDBClient(
        api_key=CONFIG["api_key"],
        language=CONFIG["language"],
        timeout=CONFIG["timeout"],
        rate_per_sec=CONFIG["rate_per_sec"],
        max_retries=CONFIG["max_retries"],
    )

    db = TVDetailDB(
        db_file=CONFIG["db_file"],
        ttl_days=CONFIG["cache_ttl_days"],
        cleanup_months=CONFIG["cleanup_months"],
    )

    mp_and_sq = MP_ADN_SQ(
        mp_url=CONFIG['mp_url'],
        mp_api_key=CONFIG['mp_api_key'],
        pushplus_token=CONFIG['pushplus_token'],
        db_file=CONFIG['db_file'],
        table_name=CONFIG['table_name']
    )

    try:
        # 1) 获取 trending ids
        ids: List[int] = []
        for page in range(1, CONFIG["pages"] + 1):
            try:
                data = client.trending_tv(CONFIG["time_window"], page)
                page_ids = [item["id"] for item in data.get("results", []) if "id" in item]
                ids.extend(page_ids)
                logging.info("抓取 trending page=%s, 数量=%s", page, len(page_ids))
            except Exception as e:
                logging.warning("trending_tv失败 page=%s err=%s", page, e)

        # 去重并保序
        seen = set()
        tv_ids: List[int] = []
        for tv_id in ids:
            if tv_id not in seen:
                seen.add(tv_id)
                tv_ids.append(tv_id)

        logging.info("去重后 tv_ids 数量=%s", len(tv_ids))

        # 2) 检查缓存，找出需要重新请求的 id
        need_fetch_ids: List[int] = []
        for tv_id in tv_ids:
            cached = db.get_cached(tv_id)
            if cached is None:
                need_fetch_ids.append(tv_id)

        logging.info("缓存命中=%s, 需重新抓取=%s", len(tv_ids) - len(need_fetch_ids), len(need_fetch_ids))

        # 3) 拉取缺失/过期详情并批量写入数据库
        fetched_items: List[Dict[str, Any]] = []
        for tv_id in need_fetch_ids:
            try:
                detail = client.tv_detail(tv_id)
                fetched_items.append(detail)
            except Exception as e:
                logging.warning("tv_detail失败 id=%s err=%s", tv_id, e)

        db.upsert_many(fetched_items)
        logging.info("本次写入/更新数据库记录数=%s", len(fetched_items))

        # 4) 用 SQL 过滤符合条件的数据
        rows = db.query_filtered_by_ids(tv_ids, CONFIG["days"])

        # 5) 转为 dict 并按 popularity 排序
        all_results: List[Dict[str, Any]] = []
        for row in rows:
            all_results.append({
                "id": row["tv_id"],
                "name": row["name"],
                "first_air_date": row["first_air_date"],
                "status": row["status"],
                "popularity": row["popularity"],
                "vote_average": row["vote_average"],
                "vote_count": row["vote_count"],
                "original_language": row["original_language"],
            })

        # 按 popularity 从高到低
        all_results.sort(key=lambda x: x.get("popularity") or 0, reverse=True)

        recent_n = all_results[:CONFIG["top_n"]]

        # 6) 打印最近n条
        mp_and_sq.init_db()
        for i, item in enumerate(recent_n, 1):
            content = f"{i}: {item.get('name')},       popularity: {item.get('popularity')}"
            print(content)
            inserted = mp_and_sq.record_string(item.get('name'))
            payload = {
                "name": item.get('name'),
                "year": str(datetime.now().year),
                "type": "电视剧",
                "resolution": "1080p",
                "filter_groups": ["中文字幕"],
                "search_imdbid": 1,
            }
            if inserted:
                if mp_and_sq.add_sub(payload):
                    mp_and_sq.pushplus('最新剧集通知', content)
                    time.sleep(2)
                else:
                    mp_and_sq.pushplus('剧集订阅失败', content)
                    time.sleep(2)
                print('\n')

        # 7) 打印全部
        # print_rows("全部符合条件数据", all_results)

    finally:
        db.close()


if __name__ == "__main__":
    main()
