import requests
import json

def add_sub(url, api_key, title, year, movie_or_tv):
    # 1. 配置基本信息

    # 2. 设置请求头 (使用 X-API-KEY 认证)
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }

    # 3. 准备请求体数据 (Payload)
    payload = {
        "tool_name": "add_subscribe",
        "arguments": {
            "title": title,
            "year": year,
            "media_type": movie_or_tv
        }
    }

    print(f"正在调用 MCP 工具: {payload['tool_name']}...")

    try:
        # 4. 发送 POST 请求
        # json=payload 会自动将字典转换为 JSON 字符串，并设置 Content-Type
        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # 5. 检查 HTTP 状态码 (如 200)
        response.raise_for_status()

        # 6. 解析 JSON 响应
        result_data = response.json()

        # 7. 根据业务逻辑判断成功与否
        print(f"结果: {result_data['result']}")

    except requests.exceptions.RequestException as e:
        # 处理网络错误 (连接超时、DNS 错误等)
        print(f"❌ 网络请求异常: {e}")
    except json.JSONDecodeError:
        # 处理返回内容不是有效 JSON 的情况
        print(f"❌ 无法解析响应内容: {response.text}")
