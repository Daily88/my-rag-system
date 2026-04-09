#API配置
OPENAI_API_KEY = "sk-737ae41763b4442dadcb9f6b1de03e4c"
OPENAI_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "deepseek-v3.2-exp"
OPENAI_EMBEDDING_MODEL = "text-embedding-v1"

# 数据目录配置
DATA_DIR = "./data"
#向量数据库配置
VECTOR_DB_PATH = "./vector_db"
COLLECTION_NAME = "course_database"
# 索引保存路径（新增，用于持久化BM25索引）
BM25_INDEX_PATH = "./bm25_index"

# 文本处理配置（对标论文600字符分块，解决原80字符知识点碎片化问题）
CHUNK_SIZE = 600
CHUNK_OVERLAP = 150
MAX_TOKENS = 2000

# RAG配置
TOP_K = 5
# 出题配置（新增）
MAX_REGEN_TIMES = 2  # 题目不合格最大重生成次数
