import sqlite3
import os
import datetime
import requests
import re
import chompjs
import http.client
import json
import time
import mp
from bs4 import BeautifulSoup

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

            # # 3. 查询表结构 (字段名, 类型, 是否主键等)
            # print("📋 表结构 (Schema):")
            # cursor.execute(f"PRAGMA table_info({table_name})")
            # columns = cursor.fetchall()
            # # 格式化输出: (序号, 字段名, 类型, ..., 主键)
            # print(f"{'CID':<5} {'字段名':<15} {'类型':<10} {'主键':<5}")
            # print("-" * 40)
            # for col in columns:
            #     # col[0]=ID, col[1]=Name, col[2]=Type, col[5]=IsPK
            #     print(f"{col[0]:<5} {col[1]:<15} {col[2]:<10} {col[5]:<5}")

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

def en_name(response:str):
    extracted_data = {}
    keys_to_extract = ['d']

    print("--- 开始提取 ---")
    for key in keys_to_extract:
        # 核心正则：匹配 _obj.key = 内容;
        pattern = re.compile(fr'_obj\.{key}(.*);', re.S)
        match = pattern.search(response)

        if match:
            js_string = match.group(1)
            # 使用 chompjs 直接转换，无需担心格式问题
            data = chompjs.parse_js_object(js_string)
            extracted_data[key] = data
            print(f"✅ 成功提取英文影名：[{extracted_data['d']['name'].strip()}]")
            return extracted_data['d']['name'].strip()
        else:
            print(f"❌ 未找到英文影名")
            return None

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

def check_new_media(username: str, password: str):
    print(f"--- 开始检查: {datetime.datetime.now()} ---")

    # 使用 Session 保持连接 (如果需要登录，请在此处添加登录逻辑)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.gying.org/",
        "Origin": "https://www.gying.org"
    })

    login_url = "https://www.gying.org/user/login"
    target_url = "https://www.gying.org"

    login_data = {
        "username": username,
        "password": password,
        "siteid": "1",
        "dosubmit": "1"
    }

    proxies = {
        # 访问 http 网站时使用的代理
        "http": http_proxy,
        # 访问 https 网站时使用的代理
        "https": http_proxy,
    }

    try:
        session.get(login_url, proxies=proxies)
        session.post(login_url, data=login_data, proxies=proxies)
        response_home = session.get(target_url, proxies=proxies)
        response_home.encoding = 'utf-8'
        # 再次确认页面里有没有你的用户名，证明 Cookie 生效
        print('*'*20 + '观影' + '*'*20)
        if username in response_home.text:
            print(">> 登陆成功。")

        extracted_data = {}
        keys_to_extract = ['header', 'inlist']

        print("--- 开始提取 ---")
        for key in keys_to_extract:
            # 核心正则：匹配 _obj.key = 内容;
            pattern = re.compile(fr'_obj\.{key}(.*);', re.S)
            match = pattern.search(response_home.text)

            if match:
                js_string = match.group(1)
                # 使用 chompjs 直接转换，无需担心格式问题
                data = chompjs.parse_js_object(js_string)
                extracted_data[key] = data
                print(f"✅ 成功提取 [{key}]")
            else:
                print(f"❌ 未找到 [{key}]")

        print("--- 提取结果验证 ---")
        print(f"用户名: {extracted_data['header']['u']['n']}")
        print(f"{extracted_data['inlist'][0]['ht']}：")
        have_new_count = 0
        for i in range(len(extracted_data['inlist'][0]['t'])):
            if 2 < extracted_data['inlist'][0]['r'][i] < 100:
                title = f"{extracted_data['inlist'][0]['t'][i]}"
                content = title + f" ({extracted_data['inlist'][0]['a'][i][0]})" + f" ⭐{extracted_data['inlist'][0]['r'][i]}万"
                is_new = check_and_save(title)
                if is_new:
                    payload = {
                        "name": extracted_data['inlist'][0]['t'][i],
                        "year": str(extracted_data['inlist'][0]['a'][i][0]),
                        "type": "电影",
                        "search_imdbid": 1,
                    }
                    if mp.add_sub(payload):
                        pushplus(pushplus_token, '最新电影通知', content)
                        have_new_count += 1
                    else:
                        tmp = session.get('https://www.gying.org/mv/' + extracted_data['inlist'][0]['i'][i], proxies=proxies)
                        name = en_name(tmp.text)
                        if name:
                            payload['name'] = name
                            print('-------尝试按照英文影名添加订阅-------')
                            if mp.add_sub(payload):
                                pushplus(pushplus_token, '最新电影通知', content)
                                have_new_count += 1
                            else:
                                delete_data(title)
                            print('\n')
        if have_new_count:
            print(f'有{have_new_count}部电影')
        else:
            print(f'无新电影')

    except Exception as e:
        print(f"发生错误: {e}")


def youku():
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.youku.com/",
    }
    response = requests.get("https://www.youku.com/ku/webmovie", headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    print('*'*20 + '优酷' + '*'*20)
    count = 0
    for i in range(3):
        element = soup.select_one(f"#swiperMode{i} > div.yk_card_368vl > a")

        if not element:
            print("未找到目标元素，页面很可能是动态渲染的，requests 获取不到最终 DOM。")
            return

        movie_title = element.get("aria-label").split()[-1]
        is_new = check_and_save(movie_title)
        if is_new:
            print("最新电影", movie_title)
            payload = {
                "name": movie_title,
                "year": str(datetime.datetime.now().year),
                "type": "电影",
                "search_imdbid": 1,
            }
            if mp.add_sub(payload):
                pushplus(pushplus_token, '最新电影通知', movie_title)
                count += 1
                time.sleep(10)
            else:
                delete_data(movie_title)
    if count == 0:
        print('无新电影')


def tencent():
    url = "https://v.qq.com/channel/movie"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://v.qq.com/'
    }

    try:
        # 1. 获取网页源码
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        html_content = response.text

        # 2. 使用正则表达式提取 focusList 后的内容
        # 匹配模式解释：找到 "focusList": 后面跟着的 [ 到 ] 之间的内容
        # re.S 模式允许 . 匹配换行符
        pattern = r'"focusList"\s*:\s*(\[.*?\])\s*(?:,|\})'
        match = re.search(pattern, html_content, re.S)

        print('*'*20 + '腾讯' + '*'*20)
        if match:
            # 提取捕获组中的字符串
            json_str = match.group(1)

            # 3. 将字符串解析为 JSON (Python 列表)
            focus_data = json.loads(json_str)

            # 4. 格式化输出关键字段
            count = 0
            for item in focus_data[0:5]:
                movie_title = item.get('title', '未知标题')
                is_new = check_and_save(movie_title)
                if is_new:
                    print("最新电影", movie_title)
                    payload = {
                        "name": movie_title,
                        "year": str(datetime.datetime.now().year),
                        "type": "电影",
                        "search_imdbid": 1,
                    }
                    if mp.add_sub(payload):
                        pushplus(pushplus_token, '最新电影通知', movie_title)
                        count += 1
                        time.sleep(10)
                    else:
                        delete_data(movie_title)
            if count == 0:
                print('无新电影')
        else:
            print("❌ 未能在源码中找到 'focusList' 数据。")
    except Exception as e:
        print(f"❌ 出错: {e}")


# --- 使用示例 ---
if __name__ == "__main__":
    # 适配青龙面板的路径逻辑
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_FILE = os.path.join(BASE_DIR, "media_history.db")
    init_db()
    pushplus_token = 'b8818418079a4c04908b3954bad91f55'
    http_proxy = 'http://192.168.110.254:7890'
    # check_and_save('极限审判')
    check_new_media('a214955582', 'zxcli1314520')
    youku()
    tencent()
    print('\n')
    clean_old_data()
    inspect_database()
