from typing import List, Dict, Optional, Tuple
import re
import json
from openai import OpenAI
from config import (
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    MODEL_NAME,
    TOP_K,
    BM25_INDEX_PATH,
    MAX_REGEN_TIMES
)
from vector_store import VectorStore
from HybridRetrieve import HybridRetriever

class RAGAgent:
    def __init__(
        self,
        model: str = MODEL_NAME,
        use_hybrid_retrieval: bool = True,
        hybrid_alpha: float = 0.7,
    ):
        self.model = model
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)
        self.vector_store = VectorStore()
        self.use_hybrid_retrieval = use_hybrid_retrieval
        
        # 初始化混合检索器，加载持久化索引
        if self.use_hybrid_retrieval:
            self.hybrid_retriever = HybridRetriever(
                self.vector_store, 
                alpha=hybrid_alpha,
                index_path=BM25_INDEX_PATH
            )
            self.is_bm25_index_built = self.hybrid_retriever.bm25_index is not None
        else:
            self.is_bm25_index_built = False

        # 系统提示词，核心要求输出JSON，禁止页码
        self.system_prompt = """你是专业的课程命题专家，只负责基于课程文档生成高质量的知识点试题。
        【绝对核心禁令（违反直接判定为不合格）】
        1. 绝对禁止生成任何关于页码、页号、文档页数、幻灯片编号、文档结构位置的题目
        2. 绝对禁止在题目、答案、解析中提及“第几页”、“位于哪一页”、“XX文档第X页”、“页码”等任何和页码相关的内容
        3. 绝对禁止考察文件名、文档格式、文档章节位置相关的内容，只考察文档中的知识点本身
        【核心命题规则】
        1. 所有题目必须100%基于提供的课程文档内容，考察文档中的核心概念、原理、方法、定理、公式、知识点
        2. 题目必须考察学生对知识点的理解和应用，而非文本细节记忆
        3. 题干清晰无歧义，选项严谨，答案准确唯一
        4. 每道题必须对应一个独立的核心知识点，不得重复考察
        5. 必须严格按照要求输出JSON格式，禁止输出任何其他无关内容
        """
        self.chat_history=[]

        # 页码禁止正则
        self.page_forbidden_pattern = re.compile(
            r'(第\s*[0-9一二三四五六七八九十百千]+\s*[页张]|页码|页\s*[0-9]+|Page\s*[0-9]+|幻灯片\s*[0-9]+|位于哪一页|哪一页.*讨论|哪一页.*涉及|pdf.*[0-9]+页)',
            re.IGNORECASE
        )

    def build_retrieval_index(self, chunks: List[Dict[str, any]]) -> None:
        """构建检索索引，构建知识库时调用"""
        if self.use_hybrid_retrieval:
            print("正在构建混合检索索引...")
            self.hybrid_retriever.build_bm25_index(chunks)
            self.is_bm25_index_built = True
            print("混合检索索引构建完成")
    
    def extract_core_knowledge(self, context: str) -> str:
        """提取文档核心知识点，二次过滤页码内容"""
        extract_prompt = f"""
        请从以下课程文档内容中，提取3-8个核心知识点，严格遵循以下规则：
        1. 每个知识点是一个独立的、可考察的概念、原理、方法、定理，绝对不要提取任何和页码、文档位置、章节编号相关的内容
        2. 只提取文档中明确提到的知识点，不要编造
        3. 每个知识点用一句话清晰描述，编号列出，不要提及任何页码、页数相关内容

        课程文档内容：
        {context}
        """
        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": extract_prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            knowledge_content = res.choices[0].message.content
            knowledge_content = self.page_forbidden_pattern.sub('', knowledge_content)
            return knowledge_content
        except Exception as e:
            print(f"知识点提取失败: {str(e)}")
            return "文档核心知识点"
    
    def filter_page_content(self, docs: List[Dict]) -> List[Dict]:
        """过滤检索结果，剔除带页码的文本块"""
        filtered_docs = []
        for doc in docs:
            content = doc.get("content", "")
            if not self.page_forbidden_pattern.search(content):
                filtered_docs.append(doc)
        return filtered_docs if filtered_docs else docs

    def retrieve_context(
        self, query: str, top_k: int = TOP_K
    ) -> Tuple[str, List[Dict]]:
        """检索相关上下文，过滤页码内容"""
        if self.use_hybrid_retrieval and self.is_bm25_index_built:
            retrieved_docs = self.hybrid_retriever.hybrid_retrieve(query, top_k=top_k*2)
        else:
            retrieved_docs=self.vector_store.search(query=query, top_k=top_k*2)
        
        filtered_docs = self.filter_page_content(retrieved_docs)[:top_k]
        
        context=[]
        for i, doc in enumerate(filtered_docs):
            content=doc.get("content", "").strip()
            metadata=doc.get("metadata", {})
            filename=metadata.get("filename", "unknown")
            doc_context=f"[材料 {i+1}]\n来源文档: {filename}\n内容: {content}\n"
            context.append(doc_context)
        
        context_str="=== 相关课程材料 ===\n" + "\n".join(context)
        return context_str, filtered_docs

    def add_documents(self, chunks: List[Dict[str, str]]) -> None:
        """添加文档并构建索引，构建知识库时调用"""
        self.vector_store.add_documents(chunks)
        if self.use_hybrid_retrieval:
            self.build_retrieval_index(chunks)
    
    def generate_response(
        self,
        query: str,
        context: str,
        chat_history: Optional[List[Dict]] = None,
    ) -> str:
        """生成问答回答"""
        messages = [{"role": "system", "content": self.system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        
        user_text = f"""
        请根据以下课程材料回答学生问题:
        ## 相关课程内容：
        {context}
        ## 学生问题：
        {query}
        ## 回答要求：
        1. 严格基于上述课程材料提供准确答案，禁止编造内容
        2. 注明知识点来自的文档名称，绝对禁止提及页码、幻灯片编号
        3. 如果材料中没有相关信息，请诚实说明
        4. 回答要简洁明了，重点突出，逻辑清晰
        请开始回答：
        """
        messages.append({"role": "user", "content": user_text})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.7, max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"生成回答时出错: {str(e)}"

    # 【核心重写】全题型适配，判断题专项修复
    def generate_questions(
        self,
        question_num: int,
        question_type: str,
        top_k: int = TOP_K
    ) -> str:
        # 1. 检索核心知识点
        context, _ = self.retrieve_context("文档核心概念、原理、方法、定理、知识点", top_k=top_k)
        if not context or "未检索到" in context:
            return "❌ 未检索到有效文档内容，请先上传文档并构建知识库"
        
        # 2. 提取核心知识点
        core_knowledge = self.extract_core_knowledge(context)
        
        # 3. 【专项修复】分题型设置规则和JSON示例
        if question_type == "选择题":
            option_rule = "每道题必须有4个选项，格式为A. 选项内容、B. 选项内容、C. 选项内容、D. 选项内容，答案唯一"
            json_example = """
            {
                "title": "题目：",
                "question_type": "选择题",
                "questions": [
                    {
                        "question_num": 1,
                        "question_stem": "在MATLAB中，用于计算x的n次方根的函数是？",
                        "options": ["A. sqrt（x）", "B. pow2（x）", "C. nthroot（x，n）", "D. exp（x）"],
                        "answer": "C",
                        "analysis": "根据文档内容，nthroot（x，n）函数专门用于计算x的n次方根，等价于sign（x）*abs（x）^（1/n）。"
                    }
                ]
            }
            """
        elif question_type == "判断题":
            option_rule = "每道题只能有2个选项，固定为A. 正确、B. 错误，禁止出现C、D等其他选项，答案只能是A或B"
            json_example = """
            {
                "title": "题目：",
                "question_type": "判断题",
                "questions": [
                    {
                        "question_num": 1,
                        "question_stem": "在Matlab中，nthroot（x，n）函数用于计算x的n次方根，其等价于sign（x）*abs（x）^（1/n）。",
                        "options": ["A. 正确", "B. 错误"],
                        "answer": "A",
                        "analysis": "根据文档中关于基本数学函数的内容，nthroot（x，n）确实用于计算x的n次方根，并明确说明其等价公式，因此该说法正确。"
                    }
                ]
            }
            """
        else:
            # 简答题规则
            option_rule = "每道题不需要选项，只需要题干、答案、解析"
            json_example = """
            {
                "title": "题目：",
                "question_type": "简答题",
                "questions": [
                    {
                        "question_num": 1,
                        "question_stem": "请简述Matlab中字符串数据类型的作用。",
                        "answer": "字符串是Matlab中用于处理文本数据的数据类型，是Matlab基础语法中的重要组成部分。",
                        "analysis": "本题考察Matlab基础数据类型的核心知识点，来自文档基础语法章节。"
                    }
                ]
            }
            """

        # 4. 【强化约束】出题Prompt
        question_prompt = f"""
        【命题任务】
        请严格基于提供的课程文档内容，生成{question_num}道{question_type}，必须100%遵守以下所有规则。
        【绝对禁止项】
        1. 绝对禁止生成任何和页码、页数、文档位置相关的题目和内容
        2. 绝对禁止编造文档中没有的知识点
        3. 绝对禁止输出任何和JSON格式无关的内容
        【题型专属规则】
        {option_rule}
        【通用命题规则】
        1. 所有题目必须考察文档中的核心知识点，包括概念定义、原理方法、公式定理、技术方案
        2. 题干清晰无歧义，答案准确唯一，符合课程考试标准
        3. 每道题必须包含题干、对应题型的选项、正确答案、解析
        4. 每道题考察不同的知识点，不得重复
        【输出要求】
        必须严格输出标准JSON格式，结构和下方示例完全一致，禁止输出任何其他内容：
        {json_example}

        【文档核心知识点】
        {core_knowledge}
        【完整课程文档内容】
        {context}
        """

        # 5. 生成+多维度校验+重生成
        question_json = None
        regen_count = 0
        while regen_count <= MAX_REGEN_TIMES:
            try:
                res = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": self.system_prompt},
                              {"role": "user", "content": question_prompt}],
                    temperature=0.6,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                generated_content = res.choices[0].message.content.strip()
                
                # 解析JSON
                question_json = json.loads(generated_content)
                
                # 校验1：禁止页码内容
                if self.page_forbidden_pattern.search(json.dumps(question_json, ensure_ascii=False)):
                    print(f"生成内容包含禁止的页码信息，第{regen_count+1}次重生成")
                    regen_count += 1
                    continue
                
                # 校验2：题目数量达标
                question_list = question_json.get("questions", [])
                if len(question_list) < question_num:
                    print(f"生成题目数量不足，第{regen_count+1}次重生成")
                    regen_count += 1
                    continue
                
                # 校验3：【判断题专项】选项数量必须为2
                if question_type == "判断题":
                    valid_question = True
                    for q in question_list:
                        if len(q.get("options", [])) != 2:
                            valid_question = False
                            break
                        # 校验选项只能是正确/错误
                        option_text = "".join(q.get("options", [])).lower()
                        if "正确" not in option_text or "错误" not in option_text:
                            valid_question = False
                            break
                    if not valid_question:
                        print(f"判断题选项不符合规范，第{regen_count+1}次重生成")
                        regen_count += 1
                        continue
                
                # 校验4：【选择题专项】选项数量必须为4
                if question_type == "选择题":
                    valid_question = True
                    for q in question_list:
                        if len(q.get("options", [])) != 4:
                            valid_question = False
                            break
                    if not valid_question:
                        print(f"选择题选项不符合规范，第{regen_count+1}次重生成")
                        regen_count += 1
                        continue
                
                break
            
            except Exception as e:
                print(f"生成/解析JSON出错: {str(e)}，第{regen_count+1}次重生成")
                regen_count += 1
        
        if not question_json:
            return "❌ 题目生成失败，请重试，或检查知识库是否正常构建"
        
        # 【核心】全题型统一强制排版，100%确保换行正确
        formatted_content = f"{question_json.get('title', '题目：')}\n{question_json.get('question_type', question_type)}\n\n"
        
        for q in question_json.get("questions", []):
            # 题干单独一行
            formatted_content += f"{q.get('question_num', 1)}. {q.get('question_stem', '')}\n"
            # 每个选项单独一行
            for opt in q.get("options", []):
                formatted_content += f"{opt}\n"
            # 答案单独一行
            formatted_content += f"答案：{q.get('answer', '')}\n"
            # 解析单独一行
            if q.get("analysis", ""):
                formatted_content += f"解析：{q.get('analysis', '')}\n"
            # 题间空一行
            formatted_content += "\n"
        
        return formatted_content.strip()

    def answer_question(
        self, query: str, chat_history: Optional[List[Dict]] = None, top_k: int = TOP_K
    ) -> Dict[str, any]:
        """回答问题"""
        context, retrieved_docs = self.retrieve_context(query, top_k=top_k)
        if not context:
            context = "（未检索到特别相关的课程材料）"
        
        if chat_history is None:
            chat_history = self.chat_history
        answer = self.generate_response(query, context, chat_history)
        self.chat_history.append({"role": "user", "content": query})
        self.chat_history.append({"role": "assistant", "content": answer})
        return {
            "answer": answer,
            "retrieved_documents": retrieved_docs,
            "context_used": context,
            "query": query,
            "retrieval_method": "hybrid" if (self.use_hybrid_retrieval and self.is_bm25_index_built) else "dense",
            "chat_history": self.chat_history
        }

    def clear_history(self):
        """清空对话历史"""
        self.chat_history = []
        print("对话历史已清空")