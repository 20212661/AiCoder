"""
litellm 延迟加载封装
统一各家 LLM API 调用接口

特性：
- 线程安全的双重检查锁定（double-check locking）
- 友好的 import 错误提示
- 环境变量统一在一处设置
"""
import threading


class LazyLiteLLM:
    """线程安全的 litellm 延迟加载器"""

    def __init__(self):
        self._module = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if name in ("_module", "_lock"):
            return object.__getattribute__(self, name)
        module = self._load()
        return getattr(module, name)

    def _load(self):
        """延迟加载 litellm（线程安全，双重检查锁定）"""
        if self._module is not None:
            return self._module

        with self._lock:
            if self._module is not None:
                return self._module

            try:
                import litellm
            except ImportError as err:
                raise ImportError(
                    "litellm is required but not installed.\n"
                    "  Install it with: pip install litellm\n"
                    "  Or reinstall aicoder: pip install -e ."
                ) from err

            litellm.suppress_debug_info = True
            litellm.drop_params = True

            # 禁止 litellm 从 GitHub 远程拉取模型价格表（避免网络超时）
            # 注：LITELLM_LOCAL_MODEL_COST_MAP 已在 main.py 入口设置
            litellm.get_model_cost_map_url = None

            self._module = litellm
            return self._module


# 模块级单例，所有消费者使用 from aicoder.llm import litellm
litellm = LazyLiteLLM()