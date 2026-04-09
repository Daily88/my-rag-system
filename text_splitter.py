from typing import List, Dict
from tqdm import tqdm
import re

class TextSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # 超强页码匹配正则，覆盖所有页码相关格式
        self.page_num_pattern = re.compile(
            r'(第\s*[0-9一二三四五六七八九十百千]+\s*[页张]|页码\s*[:：]?\s*[0-9]+|Page\s*[0-9]+|幻灯片\s*[0-9]+|^\s*[0-9]{1,3}\s*$)',
            re.IGNORECASE | re.MULTILINE
        )
        # 匹配「文档名+页码」的组合
        self.doc_page_pattern = re.compile(
            r'[a-zA-Z0-9\u4e00-\u9fa5]+\.(pdf|docx|pptx|txt)\s*第\s*[0-9]+\s*页',
            re.IGNORECASE
        )

    def clean_page_content(self, text: str) -> str:
        """【核心方法】彻底清除文本中所有页码相关内容，从源头切断页码信息"""
        # 先清除文档名+页码的组合
        text = self.doc_page_pattern.sub('', text)
        # 清除所有页码标识
        text = self.page_num_pattern.sub('', text)
        # 清除多余的空行和空格
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    def split_text(self, text: str) -> List[str]:
        """将文本切分为语义块，保证知识点完整"""
        if not text:
            return []
        
        # 先彻底清除页码内容
        text = self.clean_page_content(text)
        if not text:
            return []
        
        chunks = []
        # 中文+英文句子结束符，精准切分句子边界，保证语义完整
        sentence_end_pattern = r'([。！？.!?]\s*|\n{2,})'
        parts = re.split(sentence_end_pattern, text)
        
        # 重组句子（内容+结束符）
        sentences = []
        i = 0
        while i < len(parts):
            if i + 1 < len(parts) and re.match(sentence_end_pattern, parts[i + 1]):
                sentence = parts[i] + parts[i + 1]
                sentences.append(sentence.strip())
                i += 2
            else:
                if parts[i].strip():
                    sentences.append(parts[i].strip())
                i += 1

        # 滑动窗口切分，保证chunk_size和overlap
        current_chunk = ""
        current_length = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            # 句子本身超过chunk_size，强制截断（极端情况）
            if sentence_length > self.chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # 保留overlap
                    current_chunk = sentence[-self.chunk_overlap:] if len(sentence) > self.chunk_overlap else sentence
                    current_length = len(current_chunk)
                # 长句子分段
                for start in range(0, len(sentence), self.chunk_size - self.chunk_overlap):
                    end = start + self.chunk_size
                    sub_sentence = sentence[start:end]
                    chunks.append(sub_sentence.strip())
                continue
            
            # 正常拼接句子
            if current_length + sentence_length <= self.chunk_size:
                current_chunk += " " + sentence
                current_length += sentence_length + 1
            else:
                # 保存当前块
                chunks.append(current_chunk.strip())
                # 计算overlap，保留上一块的尾部内容
                overlap_text = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else current_chunk
                current_chunk = overlap_text + " " + sentence
                current_length = len(current_chunk)
        
        # 处理最后一个块
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # 放宽长度限制，只过滤掉超短的无效块（长度<10）
        chunks = [chunk for chunk in chunks if len(chunk) >= 10]
        return chunks

    def split_documents(self, documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """【核心方法】切分所有文档，彻底清除页码信息，所有格式统一做语义切分"""
        chunks_with_metadata = []
        for doc in tqdm(documents, desc="处理文档", unit="文档"):
            content = doc.get("content", "")
            filetype = doc.get("filetype", "")
            filename = doc.get("filename", "unknown")

            # 第一步：彻底清除内容里所有页码相关标识，从源头抹除页的概念
            cleaned_content = self.clean_page_content(content)
            if not cleaned_content.strip():
                print(f"警告：文档 {filename} 未提取到有效内容，跳过")
                continue

            # 第二步：所有文档（PDF/PPT/DOCX/TXT）统一做语义切分，不再按页拆分
            chunks = self.split_text(cleaned_content)
            if not chunks:
                print(f"警告：文档 {filename} 切分后无有效内容块，跳过")
                continue
            
            # 第三步：生成语义块，元数据彻底不保留任何页码/页号字段
            for i, chunk in enumerate(chunks):
                chunk_data = {
                    "text": chunk,
                    "content": chunk,
                    "metadata": {
                        "filename": filename,
                        "chunk_id": i,
                        "filetype": filetype
                        # 彻底删除page/page_number字段，完全不给模型看到页码信息
                    }
                }
                chunks_with_metadata.append(chunk_data)
        
        print(f"\n✅ 文档处理完成，共生成 {len(chunks_with_metadata)} 个有效语义块（已清除所有页码信息）")
        return chunks_with_metadata

def test_splitter():
    """测试方法，验证切分和页码清理功能"""
    splitter = TextSplitter(chunk_size=600, chunk_overlap=150)
    test_text = "这是一个测试句子。第71页主要涉及案例研究。文档4.3.pdf第73页讨论了相关内容。这是第二个句子！"
    cleaned = splitter.clean_page_content(test_text)
    print(f"清理后: {cleaned}")
    chunks = splitter.split_text(test_text)
    for i, chunk in enumerate(chunks):
        print(f"块 {i+1} (长度: {len(chunk)}): {chunk}")
        print("---")

if __name__ == "__main__":
    test_splitter()