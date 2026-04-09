import os
from hyber_rag_agent import RAGAgent

from config import VECTOR_DB_PATH, MODEL_NAME


def main():

    if not os.path.exists(VECTOR_DB_PATH):
        return

    # 初始化RAG Agent
    agent = RAGAgent(use_hybrid_retrieval=True, model=MODEL_NAME)

    # 检查知识库
    count = agent.vector_store.get_collection_count()
    if count == 0:
        print("error")
        return

    agent.chat()

'''
def test_vector_store():
    """测试向量存储功能"""
    print("测试向量存储...")
    agent = RAGAgent(model=MODEL_NAME)
    # 创建测试数据
    test_chunks = [
        {
            "text": "这是第一个测试文档。向量数据库是存储和检索向量的专用数据库。",
            "metadata": {"source": "test", "page": 1}
        },
        {
            "text": "这是第二个测试文档。Embedding是将文本转换为数值向量的过程。",
            "metadata": {"source": "test", "page": 2}
        },
        {
            "text": "这是第三个测试文档。ChromaDB是一个开源的向量数据库。",
            "metadata": {"source": "test", "page": 3}
        }
    ]
    
    print(f"创建了 {len(test_chunks)} 个测试文档")
    
    # 添加文档
    agent.vector_store.add_documents(test_chunks, batch_size=2)
    
    # 立即检查数量
    count = agent.vector_store.get_collection_count()
    print(f"\n测试结果: collection中的文档数量 = {count}")
    
    if count > 0:
        print("✓ 向量存储功能正常")
    else:
        print("✗ 向量存储功能异常")
# 在合适的地方调用测试
test_vector_store()
'''
if __name__ == "__main__":
    main()
