import os
from document_loader import DocumentLoader
from text_splitter import TextSplitter
from vector_store import VectorStore
from hyber_rag_agent import RAGAgent
from config import DATA_DIR, CHUNK_SIZE, CHUNK_OVERLAP, VECTOR_DB_PATH

def main():
    if not os.path.exists(DATA_DIR):
        print(f"数据目录不存在: {DATA_DIR}")
        print("请创建数据目录并放入PDF、PPTX、DOCX或TXT文件")
        return
    
    # 初始化组件
    loader = DocumentLoader(data_dir=DATA_DIR)
    splitter = TextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    vector_store = VectorStore(db_path=VECTOR_DB_PATH)
    rag_agent = RAGAgent()

    # 清空原有知识库
    vector_store.clear_collection()
    
    # 加载文档
    documents = loader.load_all_documents()
    if not documents:
        print("未找到任何有效文档")
        return
    
    # 切分文档，生成语义块
    chunks = splitter.split_documents(documents)
    if not chunks:
        print("文档切分失败，未生成有效语义块")
        return
    
    # 存储到向量数据库，同时构建混合检索索引
    print("\n正在构建知识库...")
    rag_agent.add_documents(chunks)
    
    # 校验知识库
    count = vector_store.get_collection_count()
    print(f"\n✅ 知识库构建完成！")
    print(f"向量库中文档块数量: {count}")
    print(f"混合检索索引状态: {'已构建' if rag_agent.is_bm25_index_built else '未构建'}")
    print("\n可以运行streamlit run app.py启动前端界面，或运行python main.py启动命令行对话")

if __name__ == "__main__":
    main()
