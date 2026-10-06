"""集中配置：路径、模型与 API 凭据。

设计要点（对应 PRD S-03「统一模型配置」）：

1. **导入本模块不会抛错。** 旧 `config.py` 在缺 `DEEPSEEK_API_KEY` 时 import 即 `raise`，
   逼得 5 个模块各自写一套"惰性 client"来绕开它。现在缺 Key 只在**真正调用模型**时
   由 `Settings.require_api_key()` 报错。
2. **模型名/温度/base_url 只在此定义一处**，供全部服务与 `coach.llm` 复用；
   此前 `deepseek-chat` 硬编码在 6 个文件里。
3. 路径常量（`BASE_DIR` / `DATA_DIR` / `BACKUP_DIR`）集中在此，避免各模块重复推导。
"""

import os
from dataclasses import dataclass, replace
from pathlib import Path

# 路径：本文件位于 <App_landing>/coach/config.py
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
#: 状态备份目录（`coach.storage.reset` 与 `coach.storage.state_store` 共用同一处定义）
BACKUP_DIR = DATA_DIR / "backups"

# 模型默认值（唯一来源）
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_TEMPERATURE = 0.0

# 环境变量名
API_KEY_ENV = "DEEPSEEK_API_KEY"
MODEL_ENV = "COACH_MODEL"
BASE_URL_ENV = "COACH_BASE_URL"
PRICE_IN_ENV = "COACH_PRICE_IN_PER_MTOK"
PRICE_OUT_ENV = "COACH_PRICE_OUT_PER_MTOK"


def _optional_float(raw) -> float | None:
    """把环境变量解析成 float；空值或非法值返回 None（宁缺勿错）。"""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class MissingApiKeyError(RuntimeError):
    """未配置 API Key —— 只在调用模型时抛出，不在导入时抛出。"""


@dataclass(frozen=True)
class Settings:
    """模型调用配置。frozen 以保证全局单例不会被意外改写。"""

    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = DEFAULT_TEMPERATURE
    api_key: str | None = None

    # 计费单价（每百万 token）。**默认 None = 未知**：
    # 本项目不编造价格，未配置时成本记为 null，只记录 token 用量。
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        """取 Key；缺失则抛 MissingApiKeyError（替代旧 config 的导入期崩溃）。"""
        if not self.api_key:
            raise MissingApiKeyError(
                f"未检测到 {API_KEY_ENV} 环境变量（可在调用模型前设置）"
            )
        return self.api_key

    def with_overrides(self, **kwargs) -> "Settings":
        """返回替换了部分字段的新 Settings（None 值忽略）。"""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self


def load_settings(env: dict | None = None) -> Settings:
    """从环境变量构造 Settings。缺 Key 时 api_key=None，不抛错。"""
    source = os.environ if env is None else env
    return Settings(
        model=source.get(MODEL_ENV) or DEFAULT_MODEL,
        base_url=source.get(BASE_URL_ENV) or DEFAULT_BASE_URL,
        api_key=source.get(API_KEY_ENV),
        price_in_per_mtok=_optional_float(source.get(PRICE_IN_ENV)),
        price_out_per_mtok=_optional_float(source.get(PRICE_OUT_ENV)),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """取全局 Settings（首次调用时从环境变量加载并缓存）。"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings | None) -> None:
    """覆盖全局 Settings（测试与工具用）；传 None 表示下次重新从环境加载。"""
    global _settings
    _settings = settings
