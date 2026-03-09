import requests
import json

def add_sub(payload):
    # 1. 配置基本信息
    url = "http://192.168.110.251:3000/api/v1/subscribe/"
    api_key = "fa515eb456fe4ae3bbb35ecdc694b826"  # 替换为实际的 API Key

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

def site():
    # 1. 配置基本信息
    url = "http://192.168.110.251:3000/api/v1/site/"
    api_key = "fa515eb456fe4ae3bbb35ecdc694b826"  # 替换为实际的 API Key

    # 2. 设置请求头 (使用 X-API-KEY 认证)
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    print('正在添加MP订阅...')

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


# payload = {
#     "name": "快乐老友记",
#     "year": "2023",
#     "type": "电视剧",
#     "season": 3,
#     "sites": [5, 3],
#     "search_imdbid": 1,
#     "include": "S\\d{2}E\\d{2} 20\\d{2} 2160p(.*)ADWeb",
#     "filter_groups": ["只要4K"],
# }

# payload = {
#     "name": "The Housemaid",
#     "year": "2025",
#     "type": "电影",
#     "search_imdbid": 1,
# }


# add_sub(payload)
# site()
