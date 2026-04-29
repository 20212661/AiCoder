"""
litellm 延迟加载封装
统一各家 LLM API 调用接口
"""
import os


class LazyLiteLLM:
    """延迟加载 litellm 库，避免启动时的导入开销"""

    _lazy_module = None

    def __getattr__(self, name):
        if name == "_lazy_module":
            return super().__getattribute__(name)
        self._load_litellm()
        return getattr(self._lazy_module, name)

    def _load_litellm(self):
        if self._lazy_module is not None:
            return

        # 禁止 litellm 从 GitHub 远程拉取模型价格表，避免网络超时卡住
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

        import litellm

        litellm.suppress_debug_info = True
        litellm.drop_params = True

        # 再次确保不远程获取
        litellm.get_model_cost_map_url = None

        self._lazy_module = litellm


# 模块级单例，所有消费者使用 from aicoder.llm import litellm
litellm = LazyLiteLLM()