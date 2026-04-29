"""
聊天历史摘要管理
在对话过长时自动摘要，防止超出上下文窗口
参考 Aider 的 history.py
"""
from . import prompts
from .models import Model


class ChatSummary:
    """聊天历史摘要器：在对话超出 token 预算时自动摘要"""

    def __init__(self, models=None, max_tokens=1024):
        if not models:
            models = [Model()]
        self.models = models if isinstance(models, list) else [models]
        self.max_tokens = max_tokens

    def too_big(self, messages):
        """检查消息是否超出 token 预算"""
        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)
        return total > self.max_tokens

    def tokenize(self, messages):
        """计算每条消息的 token 数量"""
        sized = []
        model = self.models[0]
        for msg in messages:
            tokens = model.token_count(msg)
            sized.append((tokens, msg))
        return sized

    def summarize(self, messages, depth=0):
        """摘要入口，确保最后一条是 assistant 消息"""
        messages = self.summarize_real(messages, depth)
        if messages and messages[-1]["role"] != "assistant":
            messages.append(dict(role="assistant", content="Ok."))
        return messages

    def summarize_real(self, messages, depth=0):
        """核心摘要算法：递归 head/tail 分割"""
        if not self.models:
            return messages

        sized = self.tokenize(messages)
        total = sum(tokens for tokens, _msg in sized)
        if total <= self.max_tokens and depth == 0:
            return messages

        min_split = 4
        if len(messages) <= min_split or depth > 3:
            return self.summarize_all(messages)

        tail_tokens = 0
        split_index = len(messages)
        half_max_tokens = self.max_tokens // 2

        # 从后往前扫描，找到 tail 的分割点
        for i in range(len(sized) - 1, -1, -1):
            tokens, _msg = sized[i]
            if tail_tokens + tokens < half_max_tokens:
                tail_tokens += tokens
                split_index = i
            else:
                break

        # 确保 head 以 assistant 消息结尾
        while messages[split_index - 1]["role"] != "assistant" and split_index > 1:
            split_index -= 1

        if split_index <= min_split:
            return self.summarize_all(messages)

        tail = messages[split_index:]
        sized_head = sized[:split_index]

        # 计算模型能处理的最大 token
        model_max_input_tokens = self.models[0].info.get("max_input_tokens") or 4096
        model_max_input_tokens -= 512

        keep = []
        total = 0
        for tokens, msg in sized_head:
            total += tokens
            if total > model_max_input_tokens:
                break
            keep.append(msg)

        summary = self.summarize_all(keep)

        # 如果 summary + tail 仍然超出，递归
        summary_tokens = self.models[0].token_count(summary)
        tail_tokens = sum(tokens for tokens, _ in sized[split_index:])
        if summary_tokens + tail_tokens < self.max_tokens:
            return summary + tail

        return self.summarize_real(summary + tail, depth + 1)

    def summarize_all(self, messages):
        """将所有消息格式化为 markdown，发送给 LLM 摘要"""
        content = ""
        for msg in messages:
            role = msg["role"].upper()
            if role not in ("USER", "ASSISTANT"):
                continue
            content += f"# {role}\n"
            content += msg["content"]
            if not content.endswith("\n"):
                content += "\n"

        summarize_messages = [
            dict(role="system", content=prompts.summarize),
            dict(role="user", content=content),
        ]

        for model in self.models:
            try:
                summary = model.simple_send(summarize_messages)
                if summary is not None:
                    summary = prompts.summary_prefix + summary
                    return [dict(role="user", content=summary)]
            except Exception as e:
                print(f"Summarization failed for model {model.name}: {e}")

        # 如果摘要失败，返回前几条消息
        return messages[:2]
