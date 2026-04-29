"""
RepoMap - 使用 tree-sitter 解析代码 AST，PageRank 排名，智能选择上下文
参考 Aider 的 repomap.py，简化版（无磁盘缓存，无 .aiderignore）
"""
import math
import os
import warnings
from collections import defaultdict, namedtuple
from importlib import resources
from pathlib import Path

from grep_ast import TreeContext, filename_to_lang

warnings.simplefilter("ignore", category=FutureWarning)
from grep_ast.tsl import USING_TSL_PACK, get_language, get_parser

Tag = namedtuple("Tag", "rel_fname fname line name kind")


class RepoMap:
    """仓库地图：智能选择最相关的代码片段放入 LLM 上下文"""

    def __init__(
        self,
        map_tokens=1024,
        root=None,
        main_model=None,
        io=None,
        repo_content_prefix=None,
        verbose=False,
    ):
        self.io = io
        self.verbose = verbose

        if not root:
            root = os.getcwd()
        self.root = root

        self.max_map_tokens = map_tokens
        self.repo_content_prefix = repo_content_prefix
        self.main_model = main_model

        self.tags_cache = {}
        self.tree_cache = {}
        self.tree_context_cache = {}
        self.map_cache = {}

    def token_count(self, text):
        """估算文本的 token 数量"""
        if self.main_model:
            return self.main_model.token_count(text)
        return len(text) // 4

    def get_repo_map(self, chat_files, other_files, mentioned_fnames=None, mentioned_idents=None):
        """生成仓库地图

        Args:
            chat_files: 已在聊天中的文件（相对路径）
            other_files: 其他仓库文件
            mentioned_fnames: 消息中提到的文件名
            mentioned_idents: 消息中提到的标识符

        Returns:
            格式化的仓库地图字符串
        """
        if not chat_files and not other_files:
            return ""

        if not other_files:
            return ""

        mentioned_fnames = set(mentioned_fnames or [])
        mentioned_idents = set(mentioned_idents or [])

        repo_map = self.get_ranked_tags_map(
            chat_files,
            other_files,
            mentioned_fnames,
            mentioned_idents,
        )

        if not repo_map:
            return ""

        prefix = self.repo_content_prefix or ""
        return prefix + repo_map

    def get_tags(self, fname, rel_fname):
        """获取文件的标签（定义和引用），带缓存"""
        # 检查 mtime
        try:
            mtime = os.path.getmtime(fname)
        except OSError:
            return []

        cached = self.tags_cache.get(fname)
        if cached and cached[0] == mtime:
            return cached[1]

        tags = self.get_tags_raw(fname, rel_fname)
        self.tags_cache[fname] = (mtime, tags)
        return tags

    def get_tags_raw(self, fname, rel_fname):
        """使用 tree-sitter 解析文件，提取定义和引用标签"""
        lang = filename_to_lang(fname)
        if not lang:
            return []

        language = get_language(lang)
        if not language:
            return []

        scm_fname = get_scm_fname(lang)
        if not scm_fname or not Path(scm_fname).exists():
            return []

        query_text = Path(scm_fname).read_text()

        code = self.io.read_text(fname)
        if not code:
            return []

        if not code.endswith("\n"):
            code += "\n"

        parser = get_parser(lang)
        tree = parser.parse(bytes(code, "utf-8"))

        try:
            query = language.query(query_text)
        except Exception:
            return []

        tags = []
        try:
            captures = self._run_captures(query, tree.root_node)
            for node, tag_kind in captures:
                tag_name = node.text.decode("utf-8")
                kind = "def" if "definition" in tag_kind else "ref"
                tags.append(Tag(rel_fname, fname, node.start_point[0], tag_name, kind))
        except Exception:
            pass

        return tags

    def _run_captures(self, query, node):
        """兼容 tree-sitter 0.23 和 0.24 API"""
        try:
            captures = query.captures(node)
            if isinstance(captures, dict):
                for tag_kind, nodes in captures.items():
                    for n in nodes:
                        yield n, tag_kind
            else:
                for n, tag_kind in captures:
                    yield n, tag_kind
        except Exception:
            return

    def get_ranked_tags(self, chat_fnames, other_fnames, mentioned_fnames, mentioned_idents):
        """使用 PageRank 排名标签

        构建引用图（谁引用了谁），运行个性化 PageRank，
        得到每个标识符的重要性分数。
        """
        try:
            import networkx as nx
        except ImportError:
            return []

        defines = defaultdict(set)
        references = defaultdict(list)
        definitions = defaultdict(set)

        # 收集所有标签
        chat_fnames = set(chat_fnames)
        other_fnames = set(other_fnames)

        for fname in chat_fnames | other_fnames:
            abs_fname = str(Path(self.root) / fname)
            if not os.path.exists(abs_fname):
                continue

            tags = self.get_tags(abs_fname, fname)
            for tag in tags:
                if tag.kind == "def":
                    defines[tag.name].add(fname)
                    definitions[tag.name].add(tag)
                elif tag.kind == "ref":
                    references[fname].append(tag.name)

        # 如果没有定义，返回空
        if not defines:
            return []

        # 构建引用图
        G = nx.MultiDiGraph()

        for fname in references:
            for ident in references[fname]:
                if ident in defines:
                    for defined_in in defines[ident]:
                        if fname != defined_in:
                            weight = 1.0

                            # 提到的标识符加权
                            if ident in mentioned_idents:
                                weight *= 10

                            # 长名称加权（更有意义的标识符）
                            if len(ident) >= 8 and ("_" in ident or ident != ident.lower()):
                                weight *= 10

                            # 聊天文件引用加权
                            if fname in chat_fnames:
                                weight *= 50

                            # 下划线前缀降权
                            if ident.startswith("_"):
                                weight *= 0.1

                            # 被很多文件定义的标识符降权
                            if len(defines[ident]) > 5:
                                weight *= 0.1

                            G.add_edge(fname, defined_in, weight=weight)

        if not G.nodes:
            return []

        # 个性化 PageRank
        personalization = {}
        for fname in chat_fnames:
            if fname in G.nodes:
                personalization[fname] = 1.0

        if not personalization:
            personalization = {n: 1.0 for n in G.nodes}

        try:
            rank = nx.pagerank(G, personalization=personalization, weight="weight")
        except Exception:
            return []

        # 给定义打分
        ranked_tags = []
        for ident in defines:
            for defined_in in defines[ident]:
                score = rank.get(defined_in, 0)
                for tag in definitions[ident]:
                    if tag.rel_fname == defined_in:
                        ranked_tags.append((score, tag))

        ranked_tags.sort(key=lambda x: (-x[0], x[1].rel_fname, x[1].line))
        return [tag for _, tag in ranked_tags]

    def get_ranked_tags_map(self, chat_fnames, other_fnames, mentioned_fnames, mentioned_idents):
        """二分搜索找到最优标签数量（不超过 token 预算）"""
        ranked_tags = self.get_ranked_tags(
            chat_fnames, other_fnames, mentioned_fnames, mentioned_idents
        )

        if not ranked_tags:
            return ""

        chat_rel_fnames = set(chat_fnames)
        lower_bound = 0
        upper_bound = len(ranked_tags)
        best_tree = ""

        while lower_bound <= upper_bound:
            middle = (lower_bound + upper_bound) // 2
            tree = self.to_tree(ranked_tags[:middle], chat_rel_fnames)
            num_tokens = self.token_count(tree)

            if num_tokens < self.max_map_tokens:
                best_tree = tree
                lower_bound = middle + 1
            else:
                upper_bound = middle - 1

        return best_tree

    def render_tree(self, abs_fname, rel_fname, lois):
        """渲染文件的树形上下文视图（只显示相关行 + 上下文）"""
        mtime = self.get_mtime(abs_fname)
        key = (rel_fname, tuple(sorted(lois)), mtime)

        if key in self.tree_cache:
            return self.tree_cache[key]

        if (
            rel_fname not in self.tree_context_cache
            or self.tree_context_cache[rel_fname]["mtime"] != mtime
        ):
            code = self.io.read_text(abs_fname) or ""
            if not code.endswith("\n"):
                code += "\n"

            context = TreeContext(
                rel_fname,
                code,
                color=False,
                line_number=False,
                child_context=False,
                last_line=False,
                margin=0,
                mark_lois=False,
                loi_pad=0,
                show_top_of_file_parent_scope=False,
            )
            self.tree_context_cache[rel_fname] = {"context": context, "mtime": mtime}

        context = self.tree_context_cache[rel_fname]["context"]
        context.lines_of_interest = set()
        context.add_lines_of_interest(lois)
        context.add_context()
        res = context.format()
        self.tree_cache[key] = res
        return res

    def to_tree(self, tags, chat_rel_fnames):
        """将排名标签列表渲染为树形视图"""
        if not tags:
            return ""

        cur_fname = None
        cur_abs_fname = None
        lois = None
        output = ""

        dummy_tag = (None,)
        for tag in sorted(tags) + [dummy_tag]:
            this_rel_fname = tag[0] if hasattr(tag, '__getitem__') else None
            if this_rel_fname in chat_rel_fnames:
                continue

            if this_rel_fname != cur_fname:
                if lois is not None:
                    output += "\n"
                    output += cur_fname + ":\n"
                    output += self.render_tree(cur_abs_fname, cur_fname, lois)
                    lois = None
                elif cur_fname:
                    output += "\n" + cur_fname + "\n"
                if type(tag) is Tag:
                    lois = []
                    cur_abs_fname = tag.fname
                cur_fname = this_rel_fname

            if lois is not None and type(tag) is Tag:
                lois.append(tag.line)

        output = "\n".join([line[:100] for line in output.splitlines()]) + "\n"
        return output

    def get_mtime(self, fname):
        try:
            return os.path.getmtime(fname)
        except OSError:
            return 0


def get_scm_fname(lang):
    """获取 tree-sitter tags 查询文件路径"""
    if USING_TSL_PACK:
        subdir = "tree-sitter-language-pack"
        try:
            path = resources.files("aider").joinpath(
                "queries", subdir, f"{lang}-tags.scm"
            )
            if path.exists():
                return path
        except Exception:
            pass

    subdir = "tree-sitter-languages"
    try:
        path = resources.files("aider").joinpath(
            "queries", subdir, f"{lang}-tags.scm"
        )
        if path.exists():
            return path
    except Exception:
        pass

    # 回退：查找本地 queries 目录
    local_queries = Path(__file__).parent / "queries"
    for subdir_name in ["tree-sitter-language-pack", "tree-sitter-languages"]:
        scm_path = local_queries / subdir_name / f"{lang}-tags.scm"
        if scm_path.exists():
            return scm_path

    return None
