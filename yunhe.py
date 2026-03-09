import sqlite3
import os
import requests
import mp
from datetime import datetime
import http.client
import json


def init_db():
    """初始化数据库表"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_media (
                title TEXT PRIMARY KEY, -- 电影标题作为主键，天然去重
                push_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

def check_and_save(title:str):
    """
    原子操作：检查是否存在，不存在则插入。
    返回: True (表示是新电影，已插入), False (表示已存在)
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            # 尝试插入数据
            # INSERT OR IGNORE: 如果主键(id)重复，则忽略本次插入，不报错
            cursor.execute(
                "INSERT OR IGNORE INTO sent_media (title) VALUES (?)",
                (title,)
            )

            # rowcount 代表受影响的行数
            # 如果是 1，说明插入成功（新电影）
            # 如果是 0，说明被 IGNORE 了（旧电影）
            if cursor.rowcount > 0:
                return True
            else:
                return False

    except Exception as e:
        print(f"数据库错误: {e}")
        return False

def inspect_database():
    print(f"📂 正在检查数据库: {DB_FILE}\n")

    if not os.path.exists(DB_FILE):
        print("❌ 错误: 数据库文件不存在！请先运行爬虫脚本生成数据库。")
        return

    try:
        # 连接数据库
        # mode='ro' 表示以只读模式打开，防止误删数据
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        cursor = conn.cursor()

        # 2. 查询数据库里有哪些表
        # sqlite_master 是 SQLite 的系统表，存放着所有元数据
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        if not tables:
            print("⚠️ 数据库是空的，没有任何表。")
            return

        for table in tables:
            table_name = table[0]
            print(f"=== 表名: 【{table_name}】 ===")

            # 4. 查询数据总数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"\n📊 数据总数: {count} 条")

            # 5. 展示最新的 5 条数据
            if count > 0:
                print("\n👀 最新 5 条数据预览:")
                cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT 5")
                rows = cursor.fetchall()
                for row in rows:
                    print(row)
            else:
                print("\n👀 表里还没有数据。")

            print("\n" + "=" * 40 + "\n")

        conn.close()

    except Exception as e:
        print(f"❌ 查询出错: {e}")

def delete_data(target_title:str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. 执行删除操作
    # 注意：请确保你的时间字段名是 push_time，表名是 sent_media
    cursor.execute(
        "DELETE FROM sent_media WHERE title = ?",
        (target_title,)
    )
    # 2. 【非常重要】提交事务
    # 如果不写这一句，程序运行不会报错，但数据库里数据根本没删掉！
    conn.commit()

    # (可选) 打印删除了多少行
    if cursor.rowcount > 0:
        print(f"成功删除: {target_title}")
    else:
        print(f"无需删除，因为未找到：{target_title}")

    conn.close()

def clean_old_data():
    print("正在清理两个月前的旧数据...")
    try:
        with sqlite3.connect(DB_FILE, isolation_level=None) as conn:
            cursor = conn.cursor()

            # 1. 执行删除操作
            # 注意：请确保你的时间字段名是 push_time，表名是 sent_media
            cursor.execute(
                "DELETE FROM sent_media WHERE push_time <= datetime('now', '-2 month')"
            )
            deleted_count = cursor.rowcount

            if deleted_count > 0:
                print(f"成功删除了 {deleted_count} 条旧记录。")

                # 2. (可选) 整理数据库文件，释放硬盘空间
                # SQLite 删除数据后不会自动变小，执行 VACUUM 会重写文件以释放空间
                cursor.execute("VACUUM")
                print("数据库已完成压缩。")
            else:
                print("没有过期的记录需要清理。")

    except Exception as e:
        print(f"清理数据时发生错误: {e}")

def is_num(char):
    if 48 <= ord(char) <= 57:
        return True
    return False

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

def filter_season(name):
    rep = {
        '第1季': 1,
        '第2季': 2,
        '第3季': 3,
        '第4季': 4,
        '第5季': 5,
        '第6季': 6,
        '第7季': 7,
        '第8季': 8,
        '第9季': 9,
        '第一季': 1,
        '第二季': 2,
        '第三季': 3,
        '第四季': 4,
        '第五季': 5,
        '第六季': 6,
        '第七季': 7,
        '第八季': 8,
        '第九季': 9,
    }
    for k,v in rep.items():
        if k in name:
            name = name[0:len(name)-3]
            return name, '0', v
    return name, str(datetime.now().year), 1

def zongyi_title(name:str):
    rep = {'第一季': 1,
           '第二季': 2,
           '第三季': 3,
           '第四季': 4,
           '第五季': 5,
           '第六季': 6,
           '第七季': 7,
           '第八季': 8,
           '第九季': 9,
           }

    if ' ' in name:
        return name.split()[0], rep[name.split()[-1]]
    else:
        return name, 1

def guoman():
    try:
        # 签到页面的 URL（通常是点击签到按钮时请求的那个地址）
        URL = "https://www.enlightent.cn/sxapi/videoTop.do"
        # 设置 User-Agent 模拟浏览器
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        }
        # 发送 GET 或 POST 请求（根据网站实际签到方式调整）
        data = {
            'channelType': 'animation',
            'day': 1,
            'rankType': '6min_no_child_new_play',
        }
        response = requests.post(URL, data=data, headers=HEADERS, timeout=10).json()
        have_new_count = 0
        for i in response['content']:
            area = i['area']
            occurDays = i['occurDays']
            if area == '中国' and occurDays < 7:
                name, year, season = filter_season(i['name'])
                is_new = check_and_save(i['name'])
                if is_new:
                    payload = {
                        "name": name,
                        "year": str(year),
                        "season": season,
                        "search_imdbid": 1,
                        "type": '电视剧',
                        "filter_groups": ["只要4K"],
                    }
                    if mp.add_sub(payload):
                        pushplus(pushplus_token, '最新国漫通知', f"{i['name']} ({datetime.now().year})")
                        have_new_count += 1
                    else:
                        delete_data(i['name'])
        if have_new_count:
            print(f'有{have_new_count}部国漫')
        else:
            print(f'无新国漫')

    except Exception as e:
        print(f"执行出错: {e}")

# def guochanju():
#     try:
#         # 签到页面的 URL（通常是点击签到按钮时请求的那个地址）
#         URL = "https://www.enlightent.cn/sxapi/top/getReboTop.do"
#         # 设置 User-Agent 模拟浏览器
#         HEADERS = {
#             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
#         }
#         response = requests.post(URL, headers=HEADERS, timeout=10).json()
#         have_new_count = 0
#         for i in response:
#             occurDays = i['occurDays']
#             heat = i['marketShare']
#             if occurDays < 5 and heat > 7:
#                 if is_num(i['name'][-1]):
#                     name = i['name'][0:len(i['name'])-1]
#                     season = int(i['name'][-1])
#                 else:
#                     name = i['name']
#                     season = 1
#                 year = datetime.now().year
#                 total_episode = i['episodeUpdated']['maxIndex']
#                 is_new = check_and_save(i['name'])
#                 if is_new:
#                     payload = {
#                         "tool_name": "add_subscribe",
#                         "arguments": {
#                             "title": name,
#                             "year": year,
#                             "season": season,
#                             "total_episode": total_episode,
#                             "media_type": '电视剧',
#                         }
#                     }
#                     mp.add_sub(payload)
#                     have_new_count += 1
#         if have_new_count:
#             print(f'有{have_new_count}部国产剧')
#         else:
#             print(f'无新国产剧')
#
#     except Exception as e:
#         print(f"执行出错: {e}")

# def zongyi():
#     try:
#         # 签到页面的 URL（通常是点击签到按钮时请求的那个地址）
#         URL = "https://www.enlightent.cn/sxapi/videoTop.do"
#         # 设置 User-Agent 模拟浏览器
#         HEADERS = {
#             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
#         }
#         # 发送 GET 或 POST 请求（根据网站实际签到方式调整）
#         data = {
#             'channelType': 'art',
#             'day': 1,
#             'rankType': 'art_hot_play',
#         }
#         response = requests.post(URL, data=data, headers=HEADERS, timeout=10).json()
#         have_new_count = 0
#         for i in response['content']:
#             occurDays = i['occurDays']
#             heat = i['marketShare']
#             if occurDays < 30 and heat > 5:
#                 name, season = filter_season(i['name'])
#                 year = datetime.now().year
#                 is_new = check_and_save(i['name'])
#                 if is_new:
#                     # payload = {
#                     #     "tool_name": "add_subscribe",
#                     #     "arguments": {
#                     #         "title": '中国唱将',
#                     #         "year": year,
#                     #         "season": 1,
#                     #         "sites": [2],
#                     #         "exclude": "(Pure|Plus|Live|Fancam|Vlog|Special|Review|Daily)",
#                     #         "filter_groups": ['只要4K'],
#                     #         "media_type": '电视剧',
#                     #     }
#                     # }
#                     # mp.add_sub(payload)
#                     pushplus(pushplus_token, '最新综艺通知', i['name'])
#                     have_new_count += 1
#         if have_new_count:
#             print(f'有{have_new_count}部综艺')
#         else:
#             print(f'无新综艺')
#
#
#     except Exception as e:
#         print(f"执行出错: {e}")

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_FILE = os.path.join(BASE_DIR, "yunhe.db")
    pushplus_token = 'b8818418079a4c04908b3954bad91f55'
    init_db()
    # guochanju()
    guoman()
    # zongyi()
    clean_old_data()
    inspect_database()
