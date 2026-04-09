'''
import os
from typing import List, Dict
import chromadb
from chromadb.config import Settings
from openai import OpenAI
from tqdm import tqdm
import time
from config import (
    VECTOR_DB_PATH,
    COLLECTION_NAME,
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    OPENAI_EMBEDDING_MODEL,
    TOP_K,
)

def sanitize_metadata(metadata: Dict) -> Dict:
    """清理metadata，彻底删除页码字段，只保留ChromaDB支持的格式"""
    import json
    sanitized = {}
    for key, value in metadata.items():
        # 【核心修改】彻底删除所有页码相关字段
        if key.lower() in ["page", "page_number", "pagenumber", "页码"]:
            continue
        if value is None:
            sanitized[key] = None
        elif isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            try:
                if all(isinstance(item, str) for item in value):
                    sanitized[key] = ", ".join(value)
                else:
                    str_list = [str(item) for item in value]
                    sanitized[key] = ", ".join(str_list)
            except Exception as e:
                sanitized[key] = str(value)
        elif isinstance(value, dict):
            try:
                sanitized[key] = json.dumps(value, ensure_ascii=False)
            except:
                sanitized[key] = str(value)
        else:
            sanitized[key] = str(value)
    return sanitized

class VectorStore:
    def __init__(
        self,
        db_path: str = VECTOR_DB_PATH,
        collection_name: str = COLLECTION_NAME,
        api_key: str = OPENAI_API_KEY,
        api_base: str = OPENAI_API_BASE,
    ):
        self.db_path = db_path
        self.collection_name = collection_name
        # 初始化OpenAI客户端
        self.client = OpenAI(api_key=api_key, base_url=api_base)
        # 初始化ChromaDB
        os.makedirs(db_path, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(
            path=db_path, settings=Settings(anonymized_telemetry=False)
        )
        # 【核心修复】获取或创建collection，确保对象一致
        self._init_collection()
        
    def _init_collection(self):
        """初始化collection，单独封装确保一致性"""
        try:
            self.collection = self.chroma_client.get_or_create_collection(
                name=self.collection_name, 
                metadata={"description": "课程材料向量数据库"}
            )
        except Exception as e:
            print(f"Collection初始化失败: {str(e)}")
            # 尝试删除旧的，重新创建
            try:
                self.chroma_client.delete_collection(name=self.collection_name)
            except:
                pass
            self.collection = self.chroma_client.create_collection(
                name=self.collection_name, 
                metadata={"description": "课程材料向量数据库"}
            )
        
    def get_embedding(self, text: str) -> List[float]:
        """获取文本的向量表示"""
        text=text.replace('\n', ' ')
        return self.client.embeddings.create(input=[text], model=OPENAI_EMBEDDING_MODEL).data[0].embedding
    
    def add_documents(self, chunks: List[Dict[str, str]], batch_size: int=200) -> None:
        """【核心重写】添加文档块到向量数据库，彻底修复Collection不存在的问题"""
        if not chunks:
            print("没有文档块可添加")
            return
        
        print(f"\n开始添加 {len(chunks)} 个文档块到向量数据库...")
        
        # 确保collection存在
        self._init_collection()
        
        total_chunks = len(chunks)
        # 减小batch_size，避免单次请求过大
        batch_size = min(batch_size, 100)
        total_batches = (total_chunks + batch_size - 1) // batch_size
        print(f"分 {total_batches} 批处理，每批 {batch_size} 个")
        
        success_count = 0
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min((batch_num + 1) * batch_size, total_chunks)
            
            print(f"\n处理第 {batch_num + 1}/{total_batches} 批 ({start_idx+1}-{end_idx})")
            
            documents = []
            metadatas = []
            ids = []
            embeddings = []
            
            # 准备数据
            for i in range(start_idx, end_idx):
                chunk = chunks[i]
                content = chunk.get("text", "") or chunk.get("content", "")
                if not content or len(content.strip()) < 10:
                    continue
                
                # 清理元数据，彻底删除页码
                metadata = chunk.get("metadata", {})
                if not metadata:
                    metadata = {
                        key: value for key, value in chunk.items()
                        if key not in ["text", "content", "embedding"]
                    }
                metadata = sanitize_metadata(metadata)
                
                # 生成embedding
                try:
                    embedding = self.get_embedding(content)
                    embeddings.append(embedding)
                    documents.append(content)
                    metadatas.append(metadata)
                    # 生成唯一ID
                    chunk_id = f"chunk_{int(time.time()*1000000)}_{i}"
                    ids.append(chunk_id)
                except Exception as e:
                    print(f"  跳过第 {i+1} 个: {str(e)}")
                    continue
            
            if not documents:
                print(f"  第 {batch_num+1} 批无有效内容")
                continue
            
            # 【核心修复】添加到向量数据库，失败则重试
            try:
                self.collection.add(
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                success_count += len(documents)
                print(f"  ✓ 第 {batch_num+1} 批成功，添加 {len(documents)} 个")
            except Exception as e:
                print(f"  ✗ 第 {batch_num+1} 批失败: {str(e)}")
                print("  尝试重新初始化Collection后重试...")
                try:
                    self._init_collection()
                    self.collection.add(
                        embeddings=embeddings,
                        documents=documents,
                        metadatas=metadatas,
                        ids=ids
                    )
                    success_count += len(documents)
                    print(f"  ✓ 重试成功，添加 {len(documents)} 个")
                except Exception as e2:
                    print(f"  ✗ 重试依然失败: {str(e2)}")
        
        print(f"\n✅ 向量数据库添加完成！共成功添加 {success_count}/{total_chunks} 个文档块")
    
    def search(self, query: str, top_k: int = TOP_K) -> List[Dict]:
        """搜索相关文档"""
        # 确保collection存在
        self._init_collection()
        
        query_embedding = self.get_embedding(query)
        results = self.collection.query(
            query_embeddings=[query_embedding], 
            n_results=top_k, 
            include=["metadatas", "documents", "distances"]
        )
        
        formatted_results = []
        if results and results['documents']:
            for i in range(len(results['documents'][0])):
                content = results['documents'][0][i]
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                distance = results['distances'][0][i] if results['distances'] else 0
                similarity_score = 1 - distance if distance <= 1 else 1 / (1 + distance)
                formatted_result = {
                    "content": content, 
                    "metadata": metadata, 
                    "similarity_score": round(similarity_score, 4)
                }
                formatted_results.append(formatted_result)
        return formatted_results
    
    def clear_collection(self) -> None:
        """【核心修复】清空collection，简化逻辑"""
        try:
            self.chroma_client.delete_collection(name=self.collection_name)
            print("旧Collection已删除")
        except Exception as e:
            print(f"删除旧Collection时提示(非致命): {str(e)}")
        # 立即创建新的
        self._init_collection()
        print("向量数据库已清空并重新初始化")
    
    def get_collection_count(self) -> int:
        """获取collection中的文档数量"""
        self._init_collection()
        return self.collection.count()
    
    def get_all_filenames(self) -> List[str]:
        """获取知识库中所有的唯一文档名称"""
        self._init_collection()
        if self.collection.count() == 0:
            return ["全部知识点"]
        # 获取所有元数据
        all_data = self.collection.get(include=["metadatas"])
        metadatas = all_data["metadatas"]
        # 提取并去重文件名
        filename_set = set()
        for meta in metadatas:
            filename = meta.get("filename", "未知文档")
            filename_set.add(filename)
        return sorted(list(filename_set))
'''
import os
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

class VectorStore:
    def __init__(self, db_path: str = "./chroma_db", embedding_model: str = "all-MiniLM-L6-v2"):
        """
        向量存储类，自动适配 Streamlit Cloud 与本地环境
        :param db_path: 本地持久化数据库路径（仅本地环境生效）
        :param embedding_model: 嵌入模型名称
        """
        # 1. 自动判断运行环境，选择对应客户端
        # Streamlit Cloud 环境使用 EphemeralClient（内存型），本地使用 PersistentClient（持久化型）
        is_streamlit_cloud = os.environ.get("STREAMLIT_RUN_ON_CLOUD", False) or "mount/src" in os.getcwd()
        
        if is_streamlit_cloud:
            # Streamlit Cloud 无状态环境：使用内存客户端
            self.chroma_client = chromadb.EphemeralClient(
                settings=Settings(anonymized_telemetry=False)
            )
            print("✅ 已适配 Streamlit Cloud 环境，使用 EphemeralClient（内存型向量库）")
        else:
            # 本地环境：使用持久化客户端，保留数据
            os.makedirs(db_path, exist_ok=True)
            self.chroma_client = chromadb.PersistentClient(
                path=db_path,
                settings=Settings(anonymized_telemetry=False)
            )
            print(f"✅ 本地环境，使用 PersistentClient，数据持久化至 {db_path}")

        # 2. 初始化嵌入函数（保持原逻辑不变）
        self.embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )

        # 3. 获取或创建集合（保持原逻辑不变）
        self.collection = self.chroma_client.get_or_create_collection(
            name="rag_collection",
            embedding_function=self.embedding_func
        )

    # -------------------------- 以下是你原有的业务方法，保持不变 --------------------------
    def add_documents(self, documents: list[str], metadatas: list[dict] = None, ids: list[str] = None):
        """向向量库添加文档"""
        if ids is None:
            ids = [f"doc_{i}" for i in range(len(documents))]
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    def search(self, query: str, top_k: int = 5):
        """根据查询检索相似文档"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )
        return results

    def clear_collection(self):
        """清空集合数据"""
        self.collection.delete(where={})