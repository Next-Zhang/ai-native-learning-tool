import os

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DEEPSEEK_API_KEY:
    raise ValueError("未检测到 DEEPSEEK_API_KEY 环境变量")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"