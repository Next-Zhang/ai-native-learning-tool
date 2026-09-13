"""embeddings.py —— 本地 BGE-M3 向量化引擎（onnxruntime 直跑官方 ONNX）。

为什么不用 fastembed / sentence-transformers：
- fastembed 白名单里没有中文 large 级模型
- sentence-transformers 依赖 PyTorch，在 Python 3.14 上装不上
- 而 BAAI/bge-m3 官方仓库直接提供了 ONNX 导出（onnx/model.onnx），
  只需 onnxruntime + tokenizers 就能在本地 CPU 上推理，零 torch 依赖。

BGE-M3 是 BAAI 的多语言旗舰 embedding 模型：
- 输出 1024 维（dense 向量）
- 输入最长 8192 token（远超我们 ≤350 token 的块）
- 中英文检索质量优秀

流程（embedding 库内部其实都做这几件事，这里显式做一遍便于学习）：
1. 下载模型文件（首次，约 2GB）：model.onnx + tokenizer.json 等 -> data/rag/models/bge-m3/
2. tokenize：文本 -> input_ids + attention_mask（按 batch 内最长 padding、8192 截断）
3. onnxruntime 推理 -> 每个 token 的向量
4. 池化：取序列首 token 的向量作为整句向量（sentence embedding 的常规做法）
5. L2 归一化（余弦检索友好，bge 官方同样归一化）

用法：
    from rag import embeddings
    model = embeddings.get_embedder()          # 首次调用会下载模型
    vecs = model.embed(["文本1", "文本2"])      # -> (n, 1024) numpy 数组
"""

import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
# 模型缓存在项目 data/ 下（已被 .gitignore 排除），不污染系统缓存、便于复现
MODEL_DIR = BASE_DIR / "data" / "rag" / "models" / "bge-m3"

HF_REPO_ID = "BAAI/bge-m3"
# 只需这几个文件就能推理（model.onnx_data 是权重，可能比 model.onnx 更大）
HF_FILES = [
    "onnx/model.onnx",
    "onnx/model.onnx_data",
    "onnx/tokenizer.json",
]

EMBED_DIM = 1024
MAX_SEQ_LEN = 8192          # BGE-M3 的最大输入长度
BATCH_SIZE = 64
PAD_TOKEN = "<pad>"          # XLM-RoBERTa 系模型的 pad token（id=1）


class BGEM3Embedder:
    """用 onnxruntime 跑 BGE-M3 的本地 embedding 引擎。"""

    def __init__(self) -> None:
        self._session = None
        self._tokenizer = None
        self._input_names: list[str] = []
        self._output_name = ""
        self.load()

    # ------------------------------------------------------------------
    # 加载：下载文件 -> tokenizer -> onnx session
    # ------------------------------------------------------------------

    def load(self) -> None:
        t0 = time.time()
        model_path, tokenizer_path = self._ensure_files()

        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        # 词表里没有 <pad> 时退化为 id=1（XLM-R 惯例）
        pad_id = self._tokenizer.token_to_id(PAD_TOKEN)
        if pad_id is None:
            pad_id = 1
        self._tokenizer.enable_padding(pad_id=pad_id, pad_token=PAD_TOKEN)
        self._tokenizer.enable_truncation(max_length=MAX_SEQ_LEN)

        import onnxruntime as ort

        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        # 不猜模型输入输出名，加载时直接读取，兼容任何 ONNX 导出
        self._input_names = [i.name for i in self._session.get_inputs()]
        self._output_name = self._session.get_outputs()[0].name
        print(
            f"BGE-M3 加载完成（{time.time() - t0:.1f}s），"
            f"输入: {self._input_names}，输出: {self._output_name}，"
            f"模型目录: {MODEL_DIR}"
        )

    def _ensure_files(self) -> tuple[Path, Path]:
        """把需要的 HF 文件下载到本地目录，返回 (model.onnx 路径, tokenizer.json 路径)。

        若文件已完整存在则直接复用，不再访问 HF（避免每次加载都触发网络检查与警告）。
        """
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        local_paths = {}
        for filename in HF_FILES:
            local = MODEL_DIR / filename
            # size>0 视为已下载完整（不完整文件通常是 0 字节的 *.incomplete）
            if local.exists() and local.stat().st_size > 0:
                local_paths[filename] = local
                continue
            from huggingface_hub import hf_hub_download

            # local_dir 模式：文件直接落到本项目目录（普通复制，无符号链接问题）
            local_paths[filename] = Path(
                hf_hub_download(
                    repo_id=HF_REPO_ID, filename=filename, local_dir=str(MODEL_DIR)
                )
            )
        return local_paths["onnx/model.onnx"], local_paths["onnx/tokenizer.json"]

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------

    def _tokenize(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """文本 -> (input_ids, attention_mask)，均为 int64，按 batch 内最长 padding。"""
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        return ids, mask

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """对一批文本一次性向量化，返回 (n, 1024) 已归一化的向量。"""
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        ids, mask = self._tokenize(texts)

        feed = {}
        for name in self._input_names:
            if name == "input_ids":
                feed[name] = ids
            elif name == "attention_mask":
                feed[name] = mask
            elif "token_type" in name:
                # BERT 系模型会要 token_type_ids；XLM-R 没有，但万一导出里有就补零
                feed[name] = np.zeros_like(ids)
            else:
                raise ValueError(f"不认识的模型输入: {name}")

        output = self._session.run([self._output_name], feed)[0]
        # 池化：输出是 (batch, seq, dim) 则取首 token（CLS），已是 (batch, dim) 则直接用
        if output.ndim == 3:
            output = output[:, 0, :]
        # L2 归一化，防止除零
        norms = np.linalg.norm(output, axis=1, keepdims=True)
        output = output / np.maximum(norms, 1e-9)
        return output.astype(np.float32)

    def embed(self, texts: list[str], batch_size: int = BATCH_SIZE):
        """分批向量化，逐个产出单条文本的 (1024,) 向量（与 fastembed 语义一致）。

        注意：内部用 embed_batch 整批推理提高吞吐，但对外按“一条文本一个向量”
        产出，避免调用方拿到整块矩阵而配对错乱。
        """
        for i in range(0, len(texts), batch_size):
            arr = self.embed_batch(texts[i : i + batch_size])
            for row in arr:               # yield 每一行，而不是整块矩阵
                yield row


# ---------------------------------------------------------------------------
# 模块级惰性单例：第一次 embed 时才真正下载模型
# ---------------------------------------------------------------------------

_embedder: BGEM3Embedder | None = None


def get_embedder() -> BGEM3Embedder:
    global _embedder
    if _embedder is None:
        _embedder = BGEM3Embedder()
    return _embedder
