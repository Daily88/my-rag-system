from typing import List, Dict, Tuple, Any
import numpy as np
from rank_bm25 import BM25Okapi
import jieba
import re
import pickle
import os

class HybridRetriever:
    def __init__(self, vector_store, alpha: float = 0.7, index_path: str = "./bm25_index"):
        """
        初始化混合检索器，对标论文2.4节
        Args:
            vector_store: 向量数据库实例
            alpha: 密集检索权重 (0-1)，稀疏检索权重为 1-alpha
            index_path: BM25索引持久化路径
        """
        self.vector_store = vector_store
        self.alpha = alpha
        self.index_path = index_path
        self.bm25_index = None
        self.documents = []
        self.metadata_list = []
        
        # 启动时尝试加载已有索引
        self._load_index()

    def _save_index(self):
        """保存BM25索引到本地，避免每次重启重新构建"""
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({
                "bm25_index": self.bm25_index,
                "documents": self.documents,
                "metadata_list": self.metadata_list
            }, f)
        print(f"BM25索引已保存至: {self.index_path}")

    def _load_index(self):
        """加载本地已保存的BM25索引"""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "rb") as f:
                    data = pickle.load(f)
                    self.bm25_index = data["bm25_index"]
                    self.documents = data["documents"]
                    self.metadata_list = data["metadata_list"]
                print(f"BM25索引加载成功，共 {len(self.documents)} 个文档")
                return True
            except Exception as e:
                print(f"BM25索引加载失败: {str(e)}")
        return False

    def build_bm25_index(self, chunks: List[Dict[str, Any]]):
        """构建BM25索引，对标论文2.4节稀疏检索"""
        self.documents = []
        self.metadata_list = []
        
        for chunk in chunks:
            content = chunk.get("text", "") or chunk.get("content", "")
            if content:
                # 中文分词
                tokenized_content = self.tokenize_chinese(content)
                self.documents.append(tokenized_content)
                self.metadata_list.append(chunk.get("metadata", {}))
        
        if self.documents:
            self.bm25_index = BM25Okapi(self.documents)
            self._save_index()
            print(f"BM25索引构建完成，共 {len(self.documents)} 个文档")
        else:
            print("警告：没有有效的文档用于构建BM25索引")
    
    def tokenize_chinese(self, text: str) -> List[str]:
        """中文分词处理，优化检索精度"""
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        # 分词，过滤停用词和单字
        words = jieba.cut(text)
        return [word for word in words if word.strip() and len(word) > 1]
    
    def dense_retrieve(self, query: str, top_k: int = 10) -> List[Dict]:
        """密集向量检索"""
        try:
            results = self.vector_store.search(query, top_k=top_k * 2)
            return results
        except Exception as e:
            print(f"密集检索失败: {str(e)}")
            return []
    
    def sparse_retrieve(self, query: str, top_k: int = 10) -> List[Dict]:
        """稀疏检索（BM25），对标论文2.4节"""
        if not self.bm25_index:
            return []
        
        try:
            tokenized_query = self.tokenize_chinese(query)
            scores = self.bm25_index.get_scores(tokenized_query)
            top_indices = np.argsort(scores)[::-1][:top_k * 2]
            
            results = []
            for idx in top_indices:
                if scores[idx] > 0:
                    results.append({
                        "content": " ".join(self.documents[idx]),
                        "metadata": self.metadata_list[idx],
                        "score": float(scores[idx]),
                        "retrieval_type": "sparse"
                    })
            return results
        except Exception as e:
            print(f"稀疏检索失败: {str(e)}")
            return []
    
    def normalize_scores(self, results: List[Dict]) -> List[Dict]:
        """归一化分数到0-1范围，保证融合公平性"""
        if not results:
            return results
        
        scores = [doc.get("score", 0) or doc.get("similarity_score", 0) for doc in results]
        max_score, min_score = max(scores), min(scores)
        if max_score == min_score:
            for doc in results:
                doc["normalized_score"] = 1.0
        else:
            for doc in results:
                raw_score = doc.get("score", 0) or doc.get("similarity_score", 0)
                doc["normalized_score"] = (raw_score - min_score) / (max_score - min_score)
        return results
    
    def hybrid_retrieve(self, query: str, top_k: int = 10) -> List[Dict]:
        """混合检索，对标论文2.4节融合策略"""
        dense_results = self.dense_retrieve(query, top_k)
        sparse_results = self.sparse_retrieve(query, top_k)
        
        dense_results = self.normalize_scores(dense_results)
        sparse_results = self.normalize_scores(sparse_results)
        
        doc_scores = {}
        # 处理密集检索结果
        for doc in dense_results:
            content = doc.get("content", "")
            if content not in doc_scores:
                doc_scores[content] = {
                    "content": content,
                    "metadata": doc.get("metadata", {}),
                    "dense_score": doc.get("normalized_score", 0),
                    "sparse_score": 0,
                    "dense_original_score": doc.get("score", 0) or doc.get("similarity_score", 0),
                    "sparse_original_score": 0
                }
            else:
                doc_scores[content]["dense_score"] = doc.get("normalized_score", 0)
                doc_scores[content]["dense_original_score"] = doc.get("score", 0) or doc.get("similarity_score", 0)
        
        # 处理稀疏检索结果
        for doc in sparse_results:
            content = doc.get("content", "")
            if content not in doc_scores:
                doc_scores[content] = {
                    "content": content,
                    "metadata": doc.get("metadata", {}),
                    "dense_score": 0,
                    "sparse_score": doc.get("normalized_score", 0),
                    "dense_original_score": 0,
                    "sparse_original_score": doc.get("score", 0)
                }
            else:
                doc_scores[content]["sparse_score"] = doc.get("normalized_score", 0)
                doc_scores[content]["sparse_original_score"] = doc.get("score", 0)
        
        # 计算混合分数
        hybrid_results = []
        for content, scores in doc_scores.items():
            hybrid_score = (self.alpha * scores["dense_score"] + (1 - self.alpha) * scores["sparse_score"])
            hybrid_results.append({
                "content": content,
                "metadata": scores["metadata"],
                "hybrid_score": hybrid_score,
                "dense_score": scores["dense_score"],
                "sparse_score": scores["sparse_score"],
                "dense_original_score": scores["dense_original_score"],
                "sparse_original_score": scores["sparse_original_score"],
                "retrieval_type": "hybrid"
            })
        
        hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return hybrid_results[:top_k]