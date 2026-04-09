'''
# ========== 最顶部：强制国内镜像配置（必须放在所有import之前） ==========
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = './hf_cache'
import streamlit as st
import shutil
import re
import uuid
from datetime import datetime
from rag_agent import RAGAgent
from config import MODEL_NAME, TOP_K, DATA_DIR
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from pptx import Presentation
from vector_store import VectorStore
# ========== 导入新拆分的模块 ==========
from exam_core import clean_option_prefix, grade_exam_answers, format_answer
from exam_ui import render_view_mode, render_test_mode, render_graded_results
# ========== 【新增】导入知识点分析模块 ==========
from knowledge_analysis import render_knowledge_analysis_page, extract_knowledge_points
# ========== Sentence-BERT 核心评分模块（保留模型加载） ==========
from sentence_transformers import SentenceTransformer
@st.cache_resource
def _load_sbert_model_internal():
    try:
        return SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    except Exception as e:
        return None
if 'model_initialized' not in st.session_state:
    st.session_state.model_initialized = False
    st.session_state.model = None
if not st.session_state.model_initialized:
    with st.spinner("正在加载语义匹配模型（仅首次加载需要1-2分钟）..."):
        loaded_model = _load_sbert_model_internal()
        if loaded_model is None:
            st.error("模型加载失败，已自动降级为关键词匹配模式")
        st.session_state.model = loaded_model
        st.session_state.model_initialized = True
model = st.session_state.model
# ========== 保留原有工具函数（保存历史、PPT加载） ==========
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
def save_exam_history(questions: list, q_type: str, knowledge_point: str, difficulty: str, agent):
    if "exam_history" not in st.session_state:
        st.session_state.exam_history = []
    
    if knowledge_point.strip():
        doc_title = knowledge_point
    else:
        try:
            doc_names = agent.vector_store.get_all_filenames()
            doc_title = "、".join(doc_names) if doc_names else "全部知识点"
        except:
            doc_title = "全部知识点"
    
    exam_id = str(uuid.uuid4())[:8]
    history_item = {
        "id": exam_id,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "doc_title": doc_title,
        "knowledge_point": knowledge_point,
        "q_type": q_type,
        "difficulty": difficulty,
        "questions": questions,
        # ========== 【新增】主界面第一次测试记录（主数据） ==========
        "main_test_record": None,
        # ========== 【新增】历史试题中心的练习记录（不影响主数据） ==========
        "practice_records": []
    }
    st.session_state.exam_history.insert(0, history_item)
    return exam_id
def load_ppt_native(file_path: str):
    prs = Presentation(file_path)
    docs = []
    for slide_num, slide in enumerate(prs.slides, 1):
        slide_text = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_text.append(shape.text)
        text_content = "\n".join(slide_text)
        if text_content.strip():
            docs.append({
                "page_content": text_content,
                "metadata": {"page": slide_num, "filename": os.path.basename(file_path)}
            })
    return docs
# ========== 页面配置 ==========
st.set_page_config(
    page_title="NLP智能题库系统",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)
if "initialized" not in st.session_state:
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.initialized = True
    st.session_state.page_state = "main"
    st.session_state.exam_history = []
    st.session_state.generated_questions = []
    st.session_state.current_q_type = ""
    st.session_state.exam_mode = "view"
    st.session_state.user_answers = {}
    st.session_state.graded = False
    st.session_state.score_detail = []
    st.session_state.total_score = 0
    # ========== 知识点分析答题记录初始化（只存主数据） ==========
    if "user_answer_records" not in st.session_state:
        st.session_state.user_answer_records = []
    # ========== 历史试卷测试状态初始化 ==========
    st.session_state.history_current_exam_id = ""
    st.session_state.history_exam_mode = "view"
    st.session_state.history_questions = []
    st.session_state.history_q_type = ""
    st.session_state.history_user_answers = {}
    st.session_state.history_graded = False
    st.session_state.history_total_score = 0
    st.session_state.history_score_detail = []
    # ========== 【新增】主界面当前生成的试卷ID ==========
    st.session_state.current_main_exam_id = ""
if "rag_agent" not in st.session_state:
    st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)
if "messages" not in st.session_state:
    st.session_state.messages = []
# ========== 左侧侧边栏 ==========
with st.sidebar:
    st.header("📂 导入课程材料")
    uploaded_files = st.file_uploader(
        "支持 PDF/DOCX/TXT/PPT/PPTX 格式",
        type=["pdf", "docx", "txt", "pptx", "ppt"],
        accept_multiple_files=True
    )
    if uploaded_files:
        if st.button("✅ 导入到知识库", use_container_width=True):
            with st.spinner("正在处理文档..."):
                os.makedirs(DATA_DIR, exist_ok=True)
                vs = VectorStore()
                all_chunks = []
                
                for uploaded_file in uploaded_files:
                    save_path = os.path.join(DATA_DIR, uploaded_file.name)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    temp_path = f"./temp_{uploaded_file.name}"
                    shutil.copyfile(save_path, temp_path)
                    
                    file_ext = temp_path.lower()
                    split_docs = []
                    
                    if file_ext.endswith(".pdf"):
                        loader = PyPDFLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".docx"):
                        loader = Docx2txtLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".txt"):
                        loader = TextLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".pptx") or file_ext.endswith(".ppt"):
                        native_ppt_docs = load_ppt_native(temp_path)
                        from langchain_core.documents import Document
                        split_docs = [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in native_ppt_docs]
                    else:
                        st.error(f"不支持的文件格式: {uploaded_file.name}")
                        os.remove(temp_path)
                        continue
                    
                    text_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=600, chunk_overlap=150,
                        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
                    )
                    split_docs = text_splitter.split_documents(split_docs)
                    
                    for doc in split_docs:
                        all_chunks.append({
                            "content": doc.page_content,
                            "metadata": {
                                "filename": uploaded_file.name,
                                "page": doc.metadata.get("page", doc.metadata.get("page_number", "unknown"))
                            }
                        })
                    
                    os.remove(temp_path)
                
                if all_chunks:
                    vs.add_documents(all_chunks)
                    st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)
                    st.success(f"✅ 导入成功！共处理 {len(all_chunks)} 个语义块")
                else:
                    st.error("❌ 未提取到有效文档内容")
    st.divider()
    
    st.header("✍️ 试题生成配置")
    knowledge_point = st.text_input(
        "核心知识点（可选）",
        placeholder="如：数据结构的二叉树遍历、英语阅读理解技巧"
    )
    q_type = st.selectbox("选择题型", ["单选", "多选", "判断", "简答"], index=0)
    difficulty = st.selectbox("难度", ["简单", "中等", "进阶"], index=1)
    num_questions = st.slider("题数", min_value=1, max_value=20, value=5)
    generate_btn = st.button("🚀 生成试题", use_container_width=True)
    st.divider()
    
    st.header("📋 历史记录")
    if st.button("📜 历史问答", use_container_width=True):
        st.session_state.page_state = "history_qa"
        st.rerun()
    if st.button("📝 历史试题", use_container_width=True):
        st.session_state.page_state = "history_exam"
        st.rerun()
    if st.button("📚 知识点分析", use_container_width=True, type="primary"):
        st.session_state.page_state = "knowledge_analysis"
        st.rerun()
    if st.button("🔙 返回对话界面", use_container_width=True):
        st.session_state.page_state = "main"
        st.rerun()
    st.divider()
    
    st.header("🔧 知识库管理")
    if st.button("🧹 清空知识库", use_container_width=True):
        vs = VectorStore()
        vs.clear_collection()
        st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)
        st.success("✅ 知识库已清空")
# ========== 主界面 ==========
if st.session_state.page_state == "main":
    if generate_btn:
        doc_count = st.session_state.rag_agent.vector_store.get_collection_count()
        if doc_count == 0:
            st.error("❌ 知识库为空，请先上传课程材料并导入到知识库")
        else:
            with st.spinner(f"正在生成{num_questions}道试题..."):
                agent = st.session_state.rag_agent
                result = agent.generate_qa(
                    knowledge_point=knowledge_point,
                    q_type=q_type,
                    difficulty=difficulty,
                    num=num_questions
                )
                
                if "❌" in result:
                    st.error(result)
                else:
                    lines = [line.strip() for line in result.split("\n") if line.strip()]
                    st.session_state.generated_questions = lines
                    st.session_state.current_q_type = q_type
                    st.session_state.exam_mode = "view"
                    st.session_state.user_answers = {}
                    st.session_state.graded = False
                    st.session_state.score_detail = []
                    st.session_state.total_score = 0
                    # ========== 【新增】保存历史并记录当前试卷ID ==========
                    exam_id = save_exam_history(lines, q_type, knowledge_point, difficulty, agent)
                    st.session_state.current_main_exam_id = exam_id
                    st.success(f"✅ 试题生成完成！已保存到历史试题中心")
    
    st.subheader("📝 生成的试题库")
    questions = st.session_state.generated_questions
    current_q_type = st.session_state.current_q_type
    total_question_num = len(questions)
    if questions:
        col1, col2, _ = st.columns([1, 1, 3])
        with col1:
            if st.button("📝 在线测试", use_container_width=True, type="primary"):
                st.session_state.exam_mode = "test"
                st.session_state.graded = False
                st.session_state.user_answers = {}
                st.session_state.score_detail = []
                st.session_state.total_score = 0
                st.rerun()
        with col2:
            if st.button("📌 查看答案", use_container_width=True):
                st.session_state.exam_mode = "view"
                st.rerun()
        
        st.divider()
        
        if st.session_state.exam_mode == "view":
            render_view_mode(questions, current_q_type)
        elif st.session_state.exam_mode == "test":
            if not st.session_state.graded:
                submitted, updated_answers = render_test_mode(
                    questions=questions,
                    current_q_type=current_q_type,
                    total_question_num=total_question_num,
                    key_prefix="main",
                    user_answers=st.session_state.user_answers
                )
                st.session_state.user_answers = updated_answers
                
                if submitted:
                    total_score, score_detail = grade_exam_answers(
                        user_answers=st.session_state.user_answers,
                        current_q_type=current_q_type,
                        total_question_num=total_question_num,
                        model=st.session_state.model
                    )
                    st.session_state.total_score = total_score
                    st.session_state.score_detail = score_detail
                    st.session_state.graded = True
                    
                    # ========== 【核心修改】主界面测试：同步到知识点分析 + 历史试题主数据 ==========
                    main_test_record = {
                        "test_id": str(uuid.uuid4())[:8],
                        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "total_score": total_score,
                        "score_detail": score_detail,
                        "user_answers": st.session_state.user_answers,
                        "q_type": current_q_type,
                        "questions": questions
                    }
                    
                    # 1. 同步到知识点分析（只存第一次）
                    for detail in score_detail:
                        knowledge_points = extract_knowledge_points(detail["title"], detail["analysis"])
                        answer_record = {
                            "knowledge_points": knowledge_points,
                            "total_score": detail["total_score"],
                            "user_score": detail["get_score"],
                            "question_title": detail["title"],
                            "is_correct": detail["is_correct"],
                            "question_type": current_q_type
                        }
                        st.session_state.user_answer_records.append(answer_record)
                    
                    # 2. 同步到历史试题的主数据（只存第一次）
                    if st.session_state.current_main_exam_id:
                        for idx, item in enumerate(st.session_state.exam_history):
                            if item["id"] == st.session_state.current_main_exam_id:
                                st.session_state.exam_history[idx]["main_test_record"] = main_test_record
                                break
                    
                    st.rerun()
            else:
                # ==================== 【彻底重写：移除重新测试按钮，只保留导出】 ====================
                # 锚点定位
                st.markdown('<a name="graded_results_main"></a>', unsafe_allow_html=True)
                st.divider()
                # 总分和等级展示
                st.markdown(f"<h2 style='text-align: center; color: #0066cc;'>📊 测试结果：{st.session_state.total_score} / 100 分</h2>", unsafe_allow_html=True)
                score = st.session_state.total_score
                if score >= 90:
                    level = "优秀"
                    level_color = "#008000"
                elif score >= 80:
                    level = "良好"
                    level_color = "#32cd32"
                elif score >= 70:
                    level = "中等"
                    level_color = "#ffd700"
                elif score >= 60:
                    level = "及格"
                    level_color = "#ffa500"
                else:
                    level = "不及格"
                    level_color = "#ff4444"
                st.markdown(f"<h3 style='text-align: center; color: {level_color};'>等级：{level}</h3>", unsafe_allow_html=True)
                st.divider()

                # 详细批改内容
                st.subheader("📝 详细批改")
                for i in range(total_question_num):
                    if i not in st.session_state.user_answers:
                        continue
                    data = st.session_state.user_answers[i]
                    title = data["title"]
                    user_ans = data["user_ans"]
                    correct_ans = data["correct_ans"]
                    analysis = data["analysis"]
                    opts = data.get("opts", [])
                    detail = next((d for d in st.session_state.score_detail if d["index"] == i+1), None)
                    
                    with st.container(border=True):
                        st.markdown(f"**Q{i+1}. {title}**")
                        
                        if current_q_type in ["单选", "多选"] and len(opts) == 4:
                            st.markdown(f"A. {opts[0]}")
                            st.markdown(f"B. {opts[1]}")
                            st.markdown(f"C. {opts[2]}")
                            st.markdown(f"D. {opts[3]}")
                            st.markdown("<br>", unsafe_allow_html=True)
                        
                        if detail:
                            st.markdown(f"<p style='font-size: 16px; font-weight: bold;'>本题总分：{detail['total_score']}分 | 你的得分：{detail['get_score']}分</p>", unsafe_allow_html=True)
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            user_display = format_answer(user_ans)
                            st.markdown(f"<p style='color: #ff4444; font-size: 16px; font-weight: bold;'>你的答案：{user_display}</p>", unsafe_allow_html=True)
                        with col2:
                            st.markdown(f"<p style='color: #0066cc; font-size: 16px; font-weight: bold;'>正确答案：{correct_ans}</p>", unsafe_allow_html=True)
                        
                        if detail:
                            status = detail["status"]
                            if status == "full":
                                st.success(f"✅ 回答正确！{detail['remark']}")
                            elif status == "partial":
                                st.warning(f"⚠️ 部分正确 | {detail['remark']}")
                            else:
                                st.error(f"❌ 回答错误 | {detail['remark']}")
                        
                        if current_q_type == "简答" and detail and detail.get("hit_detail"):
                            with st.expander("🔍 查看采分点语义匹配详情（NLP核心算法展示）", expanded=False):
                                st.markdown("**采分点命中详情：**")
                                for hd in detail["hit_detail"]:
                                    hit_status = "✅ 命中" if hd["is_hit"] else "❌ 未命中"
                                    color = "#008000" if hd["is_hit"] else "#ff4444"
                                    st.markdown(f"- 采分点：{hd['score_point']}")
                                    st.markdown(f"  匹配模式：{hd['mode']} | 相似度：<span style='color: {color}; font-weight: bold;'>{hd['similarity']}%</span> | 状态：{hit_status}", unsafe_allow_html=True)
                        
                        with st.expander("📌 查看详细解析", expanded=False):
                            formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                            st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)

                # 只保留导出按钮，彻底移除重新测试按钮
                st.divider()
                col_export, _ = st.columns([1, 1])
                with col_export:
                    export_clicked = st.button("📤 导出测试结果", use_container_width=True, type="secondary")
                    if export_clicked:
                        export_text = f"测试总分：{st.session_state.total_score}/100 分\n等级：{level}\n\n详细批改：\n"
                        for detail in st.session_state.score_detail:
                            export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                        st.download_button(
                            label="下载结果文件",
                            data=export_text,
                            file_name=f"考试结果_{st.session_state.total_score}分.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
    else:
        st.info("暂无试题，请先导入课程材料并生成试题")
    st.divider()
    
    st.subheader("💬 课程答疑助手")
    st.caption("基于你上传的课程材料，严格依据内容回答问题，支持PPT内容深度问答")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    if prompt := st.chat_input("请输入你的问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("正在检索并生成回答..."):
                agent = st.session_state.rag_agent
                answer = agent.answer(prompt)
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
# ========== 知识点掌握度分析页面 ==========
elif st.session_state.page_state == "knowledge_analysis":
    render_knowledge_analysis_page()
# ========== 【优化后】历史试题中心 ==========
elif st.session_state.page_state == "history_exam":
    st.title("📝 历史试题中心")
    st.divider()
    
    if st.session_state.exam_history:
        if st.button("🗑️ 清空全部试题记录", use_container_width=False):
            st.session_state.exam_history = []
            st.session_state.history_current_exam_id = ""
            st.session_state.history_exam_mode = "view"
            st.session_state.history_questions = []
            st.session_state.history_q_type = ""
            st.session_state.history_user_answers = {}
            st.session_state.history_graded = False
            st.session_state.history_total_score = 0
            st.session_state.history_score_detail = []
            st.success("✅ 全部试题记录已清空")
            st.rerun()
        st.divider()
    
    if st.session_state.history_current_exam_id and st.session_state.history_exam_mode in ["test", "graded"]:
        current_exam = next(
            (item for item in st.session_state.exam_history if item["id"] == st.session_state.history_current_exam_id),
            None
        )
        if current_exam:
            st.subheader(f"📝 试卷测试 | {current_exam['doc_title']} | {current_exam['q_type']}")
            if st.button("← 返回历史试题列表", use_container_width=False):
                st.session_state.history_current_exam_id = ""
                st.session_state.history_exam_mode = "view"
                st.session_state.history_questions = []
                st.session_state.history_q_type = ""
                st.session_state.history_user_answers = {}
                st.session_state.history_graded = False
                st.session_state.history_total_score = 0
                st.session_state.history_score_detail = []
                st.rerun()
            st.divider()
            
            questions = current_exam["questions"]
            q_type = current_exam["q_type"]
            total_num = len(questions)
            exam_id = current_exam["id"]
            has_main_record = current_exam["main_test_record"] is not None
            
            if st.session_state.history_exam_mode == "test":
                submitted, updated_answers = render_test_mode(
                    questions=questions,
                    current_q_type=q_type,
                    total_question_num=total_num,
                    key_prefix=f"history_{exam_id}",
                    user_answers=st.session_state.history_user_answers
                )
                st.session_state.history_user_answers = updated_answers
                
                if submitted:
                    total_score, score_detail = grade_exam_answers(
                        user_answers=st.session_state.history_user_answers,
                        current_q_type=q_type,
                        total_question_num=total_num,
                        model=st.session_state.model
                    )
                    st.session_state.history_total_score = total_score
                    st.session_state.history_score_detail = score_detail
                    st.session_state.history_graded = True
                    st.session_state.history_exam_mode = "graded"
                    
                    # ========== 【核心修改】历史试题中心测试逻辑 ==========
                    practice_record = {
                        "test_id": str(uuid.uuid4())[:8],
                        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "total_score": total_score,
                        "score_detail": score_detail,
                        "user_answers": st.session_state.history_user_answers,
                        "q_type": q_type,
                        "questions": questions
                    }
                    
                    if not has_main_record:
                        # 情况1：主界面没测过，第一次测试 → 同步到知识点分析 + 历史试题主数据
                        st.session_state.exam_history[
                            next(i for i, item in enumerate(st.session_state.exam_history) if item["id"] == exam_id)
                        ]["main_test_record"] = practice_record
                        
                        for detail in score_detail:
                            knowledge_points = extract_knowledge_points(detail["title"], detail["analysis"])
                            answer_record = {
                                "knowledge_points": knowledge_points,
                                "total_score": detail["total_score"],
                                "user_score": detail["get_score"],
                                "question_title": detail["title"],
                                "is_correct": detail["is_correct"],
                                "question_type": q_type
                            }
                            st.session_state.user_answer_records.append(answer_record)
                    else:
                        # 情况2：主界面测过，重新测试 → 只存练习记录，不影响主数据
                        st.session_state.exam_history[
                            next(i for i, item in enumerate(st.session_state.exam_history) if item["id"] == exam_id)
                        ]["practice_records"].append(practice_record)
                    
                    st.rerun()
            
            elif st.session_state.history_exam_mode == "graded":
                reset_clicked, export_clicked = render_graded_results(
                    questions=questions,
                    current_q_type=q_type,
                    total_question_num=total_num,
                    user_answers=st.session_state.history_user_answers,
                    score_detail=st.session_state.history_score_detail,
                    total_score=st.session_state.history_total_score,
                    key_prefix=f"history_{exam_id}"
                )
                
                if reset_clicked:
                    st.session_state.history_user_answers = {}
                    st.session_state.history_graded = False
                    st.session_state.history_total_score = 0
                    st.session_state.history_score_detail = []
                    st.session_state.history_exam_mode = "test"
                    st.rerun()
                
                if export_clicked:
                    level = "优秀" if st.session_state.history_total_score >=90 else "良好" if st.session_state.history_total_score >=80 else "中等" if st.session_state.history_total_score >=70 else "及格" if st.session_state.history_total_score >=60 else "不及格"
                    export_text = f"试卷：{current_exam['doc_title']}\n测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n总分：{st.session_state.history_total_score}/100 分\n等级：{level}\n\n详细批改：\n"
                    for detail in st.session_state.history_score_detail:
                        export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                    st.download_button(
                        label="下载结果文件",
                        data=export_text,
                        file_name=f"历史试卷测试结果_{st.session_state.history_total_score}分.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
        else:
            st.error("❌ 未找到该试卷，请返回历史试题列表")
            if st.button("← 返回历史试题列表"):
                st.session_state.history_current_exam_id = ""
                st.session_state.history_exam_mode = "view"
                st.rerun()
    else:
        if not st.session_state.exam_history:
            st.info("暂无试题历史记录，请先生成试题")
        else:
            for idx, item in enumerate(st.session_state.exam_history):
                exam_id = item["id"]
                q_type = item["q_type"]
                doc_title = item["doc_title"]
                create_time = item["time"]
                main_test_record = item["main_test_record"]
                practice_records = item["practice_records"]
                is_tested = main_test_record is not None
                test_tag = "✅ 已测试" if is_tested else "⚠️ 未测试"
                practice_count = f"（共{len(practice_records)}次练习）" if practice_records else ""
                
                panel_title = f"{test_tag} {practice_count} | 试卷 {exam_id} | {q_type} | {doc_title} | {create_time}"
                with st.expander(panel_title, expanded=False):
                    if st.button(f"❌ 删除本组", key=f"del_exam_{exam_id}"):
                        st.session_state.exam_history.pop(idx)
                        st.success("✅ 本组试题已删除")
                        st.rerun()
                    
                    st.divider()
                    
                    if is_tested:
                        st.subheader("📊 主界面第一次测试记录（主数据）")
                        st.metric(
                            label="测试得分",
                            value=f"{main_test_record['total_score']}/100分",
                            delta=f"测试时间：{main_test_record['test_time']}"
                        )
                        
                        if st.button("📋 查看本次答题详情", key=f"view_main_{exam_id}"):
                            st.session_state.history_current_exam_id = exam_id
                            st.session_state.history_exam_mode = "graded"
                            st.session_state.history_questions = main_test_record["questions"]
                            st.session_state.history_q_type = main_test_record["q_type"]
                            st.session_state.history_user_answers = main_test_record["user_answers"]
                            st.session_state.history_total_score = main_test_record["total_score"]
                            st.session_state.history_score_detail = main_test_record["score_detail"]
                            st.session_state.history_graded = True
                            st.rerun()
                        
                        if st.button("📤 导出本次测试结果", key=f"export_main_{exam_id}"):
                            level = "优秀" if main_test_record['total_score'] >=90 else "良好" if main_test_record['total_score'] >=80 else "中等" if main_test_record['total_score'] >=70 else "及格" if main_test_record['total_score'] >=60 else "不及格"
                            export_text = f"试卷：{doc_title}\n测试时间：{main_test_record['test_time']}\n总分：{main_test_record['total_score']}/100 分\n等级：{level}\n\n详细批改：\n"
                            for detail in main_test_record["score_detail"]:
                                export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                            st.download_button(
                                label="下载结果文件",
                                data=export_text,
                                file_name=f"主界面测试结果_{main_test_record['total_score']}分_{main_test_record['test_time'].replace(' ', '_')}.txt",
                                mime="text/plain",
                                use_container_width=True,
                                key=f"download_main_{exam_id}"
                            )
                        
                        if practice_records:
                            st.divider()
                            st.subheader("📝 历史练习记录（不影响主数据）")
                            practice_options = [
                                f"{record['test_time']} | 得分：{record['total_score']}/100分"
                                for record in practice_records
                            ]
                            selected_practice_idx = st.selectbox(
                                "选择要查看的练习记录",
                                options=range(len(practice_options)),
                                format_func=lambda x: practice_options[x],
                                key=f"select_practice_{exam_id}"
                            )
                            selected_practice = practice_records[selected_practice_idx]
                            
                            if st.button("📋 查看本次练习详情", key=f"view_practice_{exam_id}"):
                                st.session_state.history_current_exam_id = exam_id
                                st.session_state.history_exam_mode = "graded"
                                st.session_state.history_questions = selected_practice["questions"]
                                st.session_state.history_q_type = selected_practice["q_type"]
                                st.session_state.history_user_answers = selected_practice["user_answers"]
                                st.session_state.history_total_score = selected_practice["total_score"]
                                st.session_state.history_score_detail = selected_practice["score_detail"]
                                st.session_state.history_graded = True
                                st.rerun()
                            
                            if st.button("📤 导出本次练习结果", key=f"export_practice_{exam_id}"):
                                level = "优秀" if selected_practice['total_score'] >=90 else "良好" if selected_practice['total_score'] >=80 else "中等" if selected_practice['total_score'] >=70 else "及格" if selected_practice['total_score'] >=60 else "不及格"
                                export_text = f"试卷：{doc_title}\n练习时间：{selected_practice['test_time']}\n总分：{selected_practice['total_score']}/100 分\n等级：{level}\n\n详细批改：\n"
                                for detail in selected_practice["score_detail"]:
                                    export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                                st.download_button(
                                    label="下载结果文件",
                                    data=export_text,
                                    file_name=f"历史练习结果_{selected_practice['total_score']}分_{selected_practice['test_time'].replace(' ', '_')}.txt",
                                    mime="text/plain",
                                    use_container_width=True,
                                    key=f"download_practice_{exam_id}"
                                )
                        
                        st.divider()
                    
                    st.subheader("📌 题目与答案查看")
                    render_view_mode(item["questions"], item["q_type"])
                    
                    st.divider()
                    
                    button_text = "🔄 重新测试（仅练习）" if is_tested else "📝 开始测试"
                    if st.button(button_text, use_container_width=True, type="primary", key=f"start_test_{exam_id}"):
                        st.session_state.history_current_exam_id = exam_id
                        st.session_state.history_exam_mode = "test"
                        st.session_state.history_questions = item["questions"]
                        st.session_state.history_q_type = item["q_type"]
                        st.session_state.history_user_answers = {}
                        st.session_state.history_graded = False
                        st.session_state.history_total_score = 0
                        st.session_state.history_score_detail = []
                        st.rerun()
# ========== 历史问答界面 ==========
elif st.session_state.page_state == "history_qa":
    st.title("📜 历史问答记录")
    st.divider()
    if st.session_state.messages:
        qa_pairs = []
        for i in range(0, len(st.session_state.messages), 2):
            if i+1 < len(st.session_state.messages):
                user_msg = st.session_state.messages[i]
                assistant_msg = st.session_state.messages[i+1]
                if user_msg["role"] == "user" and assistant_msg["role"] == "assistant":
                    qa_pairs.append((user_msg["content"], assistant_msg["content"]))
        
        for i, (question, answer) in enumerate(qa_pairs, 1):
            with st.container(border=True):
                st.markdown(f"**👤 问题 {i}：** {question}")
                st.markdown(f"**🤖 回答：** {answer}")
            st.divider()
        
        if st.button("🗑️ 清空全部问答记录", use_container_width=False):
            st.session_state.messages = []
            st.success("✅ 全部问答记录已清空")
            st.rerun()
    else:
        st.info("暂无问答历史记录，请先在对话界面提问")
st.divider()
st.caption("💡 NLP智能题库系统 | 基于Sentence-BERT语义匹配 | 国内网络优化 | 在线作答 | 精准评分 | 自动批改 | 历史记录")
'''
# ========== 最顶部：强制国内镜像配置（必须放在所有import之前） ==========
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = './hf_cache'
import streamlit as st
import shutil
import re
import uuid
from datetime import datetime
from rag_agent import RAGAgent
from config import MODEL_NAME, TOP_K, DATA_DIR
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from pptx import Presentation
from vector_store import VectorStore
# ========== 导入拆分的模块 ==========
from exam_core import clean_option_prefix, grade_exam_answers, format_answer
from exam_ui import render_view_mode, render_test_mode, render_graded_results
# ========== 知识点分析模块 ==========
from knowledge_analysis import render_knowledge_analysis_page, extract_knowledge_points
# ========== Sentence-BERT 核心评分模块 ==========
from sentence_transformers import SentenceTransformer

# ========== 全局SSL配置 ==========
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ========== 模型加载（原有逻辑完整保留） ==========
@st.cache_resource
def _load_sbert_model_internal():
    try:
        return SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    except Exception as e:
        return None

if 'model_initialized' not in st.session_state:
    st.session_state.model_initialized = False
    st.session_state.model = None
if not st.session_state.model_initialized:
    with st.spinner("正在加载语义匹配模型（仅首次加载需要1-2分钟）..."):
        loaded_model = _load_sbert_model_internal()
        if loaded_model is None:
            st.error("模型加载失败，已自动降级为关键词匹配模式")
        st.session_state.model = loaded_model
        st.session_state.model_initialized = True
model = st.session_state.model

# ========== 工具函数（完整保留原有逻辑） ==========
def save_exam_history(questions: list, q_type: str, knowledge_point: str, difficulty: str, agent):
    if "exam_history" not in st.session_state:
        st.session_state.exam_history = []
    
    if knowledge_point.strip():
        doc_title = knowledge_point
    else:
        try:
            doc_names = agent.vector_store.get_all_filenames()
            doc_title = "、".join(doc_names) if doc_names else "全部知识点"
        except:
            doc_title = "全部知识点"
    
    exam_id = str(uuid.uuid4())[:8]
    history_item = {
        "id": exam_id,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "doc_title": doc_title,
        "knowledge_point": knowledge_point,
        "q_type": q_type,
        "difficulty": difficulty,
        "questions": questions,
        "main_test_record": None,
        "practice_records": []
    }
    st.session_state.exam_history.insert(0, history_item)
    return exam_id

def load_ppt_native(file_path: str):
    prs = Presentation(file_path)
    docs = []
    for slide_num, slide in enumerate(prs.slides, 1):
        slide_text = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_text.append(shape.text)
        text_content = "\n".join(slide_text)
        if text_content.strip():
            docs.append({
                "page_content": text_content,
                "metadata": {"page": slide_num, "filename": os.path.basename(file_path)}
            })
    return docs

# ========== 页面配置 ==========
st.set_page_config(
    page_title="智能出题与在线测试",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== session_state 全量初始化（新增错题本和上传组件状态） ==========
if "initialized" not in st.session_state:
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.initialized = True
    st.session_state.page_state = "main"  # 默认智能出题页
    # 原有试题相关状态
    st.session_state.exam_history = []
    st.session_state.generated_questions = []
    st.session_state.current_q_type = ""
    st.session_state.exam_mode = "view"
    st.session_state.user_answers = {}
    st.session_state.graded = False
    st.session_state.score_detail = []
    st.session_state.total_score = 0
    # 知识点分析答题记录
    if "user_answer_records" not in st.session_state:
        st.session_state.user_answer_records = []
    # 历史试卷相关状态（仅保留查看能力，移除测试逻辑）
    st.session_state.history_current_exam_id = ""
    st.session_state.history_questions = []
    st.session_state.history_q_type = ""
    # 智能问答消息
    if "messages" not in st.session_state:
        st.session_state.messages = []
    # ========== 【新增】错题本专属状态 ==========
    st.session_state.wrong_questions = []  # 归集的错题列表
    st.session_state.wrong_exam_mode = "view"  # view:错题查看 test:错题重测 graded:批改结果
    st.session_state.wrong_user_answers = {}  # 错题作答答案
    st.session_state.wrong_graded = False  # 错题批改状态
    st.session_state.wrong_total_score = 0  # 错题测试总分
    st.session_state.wrong_score_detail = []  # 错题批改详情
    st.session_state.selected_wrong_ids = []  # 选中的重测错题ID
    # ========== 【新增】文件上传组件重置key ==========
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

# RAG Agent 初始化
if "rag_agent" not in st.session_state:
    st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)

# ========== 左侧侧边栏：文档导入 + 功能导航 ==========
with st.sidebar:
    # 文档导入区域
    st.header("📂 文档导入")
    st.caption("支持 PDF/DOCX/TXT/PPT/PPTX 格式")
    uploaded_files = st.file_uploader(
        "将文件拖拽到此处或点击上传",
        type=["pdf", "docx", "txt", "pptx", "ppt"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        # ========== 【修改】添加动态key，清空后自动重置组件 ==========
        key=f"file_uploader_{st.session_state.uploader_key}"
    )

    # 文档导入处理逻辑（完整保留原有）
    if uploaded_files:
        if st.button("✅ 导入到知识库", use_container_width=True):
            with st.spinner("正在处理文档..."):
                os.makedirs(DATA_DIR, exist_ok=True)
                vs = VectorStore()
                all_chunks = []
                
                for uploaded_file in uploaded_files:
                    save_path = os.path.join(DATA_DIR, uploaded_file.name)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    temp_path = f"./temp_{uploaded_file.name}"
                    shutil.copyfile(save_path, temp_path)
                    
                    file_ext = temp_path.lower()
                    split_docs = []
                    
                    if file_ext.endswith(".pdf"):
                        loader = PyPDFLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".docx"):
                        loader = Docx2txtLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".txt"):
                        loader = TextLoader(temp_path)
                        split_docs = loader.load()
                    elif file_ext.endswith(".pptx") or file_ext.endswith(".ppt"):
                        native_ppt_docs = load_ppt_native(temp_path)
                        from langchain_core.documents import Document
                        split_docs = [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in native_ppt_docs]
                    else:
                        st.error(f"不支持的文件格式: {uploaded_file.name}")
                        os.remove(temp_path)
                        continue
                    
                    text_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=600, chunk_overlap=150,
                        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
                    )
                    split_docs = text_splitter.split_documents(split_docs)
                    
                    for doc in split_docs:
                        all_chunks.append({
                            "content": doc.page_content,
                            "metadata": {
                                "filename": uploaded_file.name,
                                "page": doc.metadata.get("page", doc.metadata.get("page_number", "unknown"))
                            }
                        })
                    
                    os.remove(temp_path)
                
                if all_chunks:
                    vs.add_documents(all_chunks)
                    st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)
                    st.success(f"✅ 导入成功！共处理 {len(all_chunks)} 个语义块")
                else:
                    st.error("❌ 未提取到有效文档内容")

    st.divider()

    # 功能导航区域
    st.header("📋 功能导航")
    # 智能出题按钮
    if st.button("📝 智能出题", 
                 type="primary" if st.session_state.page_state == "main" else "secondary",
                 use_container_width=True):
        st.session_state.page_state = "main"
        st.rerun()
    # 智能问答按钮
    if st.button("💬 智能问答",
                 type="primary" if st.session_state.page_state == "qa" else "secondary",
                 use_container_width=True):
        st.session_state.page_state = "qa"
        st.rerun()
    # 历史试卷按钮
    if st.button("📜 历史试卷",
                 type="primary" if st.session_state.page_state == "history_exam" else "secondary",
                 use_container_width=True):
        st.session_state.page_state = "history_exam"
        st.rerun()
    # 知识点分析按钮
    if st.button("📊 知识点分析",
                 type="primary" if st.session_state.page_state == "knowledge_analysis" else "secondary",
                 use_container_width=True):
        st.session_state.page_state = "knowledge_analysis"
        st.rerun()
    # 我的错题本按钮（唯一保留重测功能的入口）
    if st.button("❌ 我的错题本",
                 type="primary" if st.session_state.page_state == "wrong_book" else "secondary",
                 use_container_width=True):
        st.session_state.page_state = "wrong_book"
        # 进入错题本时自动刷新错题列表
        st.session_state.wrong_questions = [
            record for record in st.session_state.user_answer_records
            if not record["is_correct"]
        ]
        st.rerun()

    st.divider()

    # ========== 【核心修改】清空知识库按钮（彻底删除本地文件+重置界面） ==========
    if st.button("🧹 清空知识库", use_container_width=True):
        with st.spinner("正在清空知识库..."):
            # 1. 清空向量数据库集合
            vs = VectorStore()
            vs.clear_collection()
            
            # 2. 彻底删除后台data文件夹内的所有文件
            if os.path.exists(DATA_DIR):
                for filename in os.listdir(DATA_DIR):
                    file_path = os.path.join(DATA_DIR, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        st.error(f"删除文件失败：{filename}，错误信息：{e}")
            
            # 3. 重新初始化RAG Agent
            st.session_state.rag_agent = RAGAgent(model=MODEL_NAME, top_k=TOP_K)
            
            # 4. 重置文件上传组件
            st.session_state.uploader_key += 1
            
            # 5. 成功提示
            st.success("✅ 知识库已清空")
            st.rerun()

# ========== 页面路由渲染 ==========
# 1. 智能出题主页面（彻底移除重新测试功能）
if st.session_state.page_state == "main":
    # 页面标题
    st.markdown("<h1 style='text-align: center; margin-top: 2rem; margin-bottom: 3rem;'>📑 智能出题与在线测试</h1>", unsafe_allow_html=True)
    st.divider()

    # 横向出题配置面板
    col_knowledge, col_type, col_difficulty, col_num = st.columns([2.5, 1.5, 1.5, 1.5])
    with col_knowledge:
        knowledge_point = st.text_input(
            "核心知识点",
            placeholder="例如：唯物论、导数、Python",
            label_visibility="visible"
        )
    with col_type:
        q_type = st.selectbox("题型", ["单选", "多选", "判断", "简答"], index=0, label_visibility="visible")
    with col_difficulty:
        difficulty = st.selectbox("难度", ["简单", "中等", "进阶"], index=1, label_visibility="visible")
    with col_num:
        num_questions = st.slider("题目数量", min_value=1, max_value=20, value=5, label_visibility="visible")

    # 生成试题按钮
    st.markdown("<br>", unsafe_allow_html=True)
    generate_btn = st.button("🚀 生成试题", use_container_width=True, type="primary")
    st.divider()

    # 底部说明文字
    st.caption("🟣 智能题库系统 | 适配全学科学生使用 | 基于RAG与大语言模型")

    # 试题生成逻辑
    if generate_btn:
        doc_count = st.session_state.rag_agent.vector_store.get_collection_count()
        if doc_count == 0:
            st.error("❌ 知识库为空，请先上传课程材料并导入到知识库")
        else:
            with st.spinner(f"正在生成{num_questions}道试题..."):
                agent = st.session_state.rag_agent
                result = agent.generate_qa(
                    knowledge_point=knowledge_point,
                    q_type=q_type,
                    difficulty=difficulty,
                    num=num_questions
                )
                
                if "❌" in result:
                    st.error(result)
                else:
                    lines = [line.strip() for line in result.split("\n") if line.strip()]
                    st.session_state.generated_questions = lines
                    st.session_state.current_q_type = q_type
                    st.session_state.exam_mode = "view"
                    st.session_state.user_answers = {}
                    st.session_state.graded = False
                    st.session_state.score_detail = []
                    st.session_state.total_score = 0
                    # 保存历史记录
                    exam_id = save_exam_history(lines, q_type, knowledge_point, difficulty, agent)
                    st.session_state.current_main_exam_id = exam_id
                    st.success(f"✅ 试题生成完成！已保存到历史试卷")

    # 试题展示与测试逻辑（仅保留一次测试能力，无重新测试）
    st.divider()
    st.subheader("📝 生成的试题库")
    questions = st.session_state.generated_questions
    current_q_type = st.session_state.current_q_type
    total_question_num = len(questions)

    if questions:
        # 仅保留「在线测试」和「查看答案」按钮，无重新测试
        col1, col2, _ = st.columns([1, 1, 3])
        with col1:
            if st.button("📝 在线测试", use_container_width=True, type="primary"):
                st.session_state.exam_mode = "test"
                st.session_state.graded = False
                st.session_state.user_answers = {}
                st.session_state.score_detail = []
                st.session_state.total_score = 0
                st.rerun()
        with col2:
            if st.button("📌 查看答案", use_container_width=True):
                st.session_state.exam_mode = "view"
                st.rerun()
        
        st.divider()
        
        # 查看答案模式
        if st.session_state.exam_mode == "view":
            render_view_mode(questions, current_q_type)
        # 在线测试模式（仅首次可测，无重测入口）
        elif st.session_state.exam_mode == "test":
            if not st.session_state.graded:
                submitted, updated_answers = render_test_mode(
                    questions=questions,
                    current_q_type=current_q_type,
                    total_question_num=total_question_num,
                    key_prefix="main",
                    user_answers=st.session_state.user_answers
                )
                st.session_state.user_answers = updated_answers
                
                if submitted:
                    total_score, score_detail = grade_exam_answers(
                        user_answers=st.session_state.user_answers,
                        current_q_type=current_q_type,
                        total_question_num=total_question_num,
                        model=st.session_state.model
                    )
                    st.session_state.total_score = total_score
                    st.session_state.score_detail = score_detail
                    st.session_state.graded = True
                    
                    # 同步到知识点分析和历史记录
                    main_test_record = {
                        "test_id": str(uuid.uuid4())[:8],
                        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "total_score": total_score,
                        "score_detail": score_detail,
                        "user_answers": st.session_state.user_answers,
                        "q_type": current_q_type,
                        "questions": questions
                    }
                    
                    # 同步到知识点分析
                    for detail in score_detail:
                        knowledge_points = extract_knowledge_points(detail["title"], detail["analysis"])
                        answer_record = {
                            "knowledge_points": knowledge_points,
                            "total_score": detail["total_score"],
                            "user_score": detail["get_score"],
                            "question_title": detail["title"],
                            "is_correct": detail["is_correct"],
                            "question_type": current_q_type
                        }
                        st.session_state.user_answer_records.append(answer_record)
                    
                    # 同步到历史记录
                    if st.session_state.current_main_exam_id:
                        for idx, item in enumerate(st.session_state.exam_history):
                            if item["id"] == st.session_state.current_main_exam_id:
                                st.session_state.exam_history[idx]["main_test_record"] = main_test_record
                                break
                    
                    st.rerun()
            # 批改结果（仅保留导出，彻底移除重新测试）
            else:
                st.markdown('<a name="graded_results_main"></a>', unsafe_allow_html=True)
                st.divider()
                # 总分和等级展示
                st.markdown(f"<h2 style='text-align: center;'>📊 测试结果：{st.session_state.total_score} / 100 分</h2>", unsafe_allow_html=True)
                score = st.session_state.total_score
                if score >= 90:
                    level = "优秀"
                    level_color = "#008000"
                elif score >= 80:
                    level = "良好"
                    level_color = "#32cd32"
                elif score >= 70:
                    level = "中等"
                    level_color = "#ffd700"
                elif score >= 60:
                    level = "及格"
                    level_color = "#ffa500"
                else:
                    level = "不及格"
                    level_color = "#ff4444"
                st.markdown(f"<h3 style='text-align: center; color: {level_color};'>等级：{level}</h3>", unsafe_allow_html=True)
                st.divider()
                # 详细批改内容
                st.subheader("📝 详细批改")
                for i in range(total_question_num):
                    if i not in st.session_state.user_answers:
                        continue
                    data = st.session_state.user_answers[i]
                    title = data["title"]
                    user_ans = data["user_ans"]
                    correct_ans = data["correct_ans"]
                    analysis = data["analysis"]
                    opts = data.get("opts", [])
                    detail = next((d for d in st.session_state.score_detail if d["index"] == i+1), None)
                    
                    with st.container(border=True):
                        st.markdown(f"**Q{i+1}. {title}**")
                        
                        if current_q_type in ["单选", "多选"] and len(opts) == 4:
                            st.markdown(f"A. {opts[0]}")
                            st.markdown(f"B. {opts[1]}")
                            st.markdown(f"C. {opts[2]}")
                            st.markdown(f"D. {opts[3]}")
                            st.markdown("<br>", unsafe_allow_html=True)
                        
                        if detail:
                            st.markdown(f"**本题总分：{detail['total_score']}分 | 你的得分：{detail['get_score']}分**")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            user_display = format_answer(user_ans)
                            st.markdown(f"<p style='color: #ff4444; font-weight: bold;'>你的答案：{user_display}</p>", unsafe_allow_html=True)
                        with col2:
                            st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>正确答案：{correct_ans}</p>", unsafe_allow_html=True)
                        
                        if detail:
                            status = detail["status"]
                            if status == "full":
                                st.success(f"✅ 回答正确！{detail['remark']}")
                            elif status == "partial":
                                st.warning(f"⚠️ 部分正确 | {detail['remark']}")
                            else:
                                st.error(f"❌ 回答错误 | {detail['remark']}")
                        
                        if current_q_type == "简答" and detail and detail.get("hit_detail"):
                            with st.expander("🔍 查看采分点语义匹配详情", expanded=False):
                                st.markdown("**采分点命中详情：**")
                                for hd in detail["hit_detail"]:
                                    hit_status = "✅ 命中" if hd["is_hit"] else "❌ 未命中"
                                    color = "#008000" if hd["is_hit"] else "#ff4444"
                                    st.markdown(f"- 采分点：{hd['score_point']}")
                                    st.markdown(f"  匹配模式：{hd['mode']} | 相似度：<span style='color: {color}; font-weight: bold;'>{hd['similarity']}%</span> | 状态：{hit_status}", unsafe_allow_html=True)
                        
                        with st.expander("📌 查看详细解析", expanded=False):
                            formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                            st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                # 仅保留导出按钮，彻底移除重新测试
                st.divider()
                col_export, _ = st.columns([1, 1])
                with col_export:
                    export_clicked = st.button("📤 导出测试结果", use_container_width=True)
                    if export_clicked:
                        export_text = f"测试总分：{st.session_state.total_score}/100 分\n等级：{level}\n\n详细批改：\n"
                        for detail in st.session_state.score_detail:
                            export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                        st.download_button(
                            label="下载结果文件",
                            data=export_text,
                            file_name=f"考试结果_{st.session_state.total_score}分.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
    else:
        st.info("暂无试题，请先导入课程材料并生成试题")

# 2. 智能问答页面（完整保留原有逻辑）
elif st.session_state.page_state == "qa":
    st.title("💬 课程智能问答助手")
    st.caption("基于你上传的课程材料，严格依据内容回答问题，支持PPT内容深度问答")
    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("请输入你的问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("正在检索并生成回答..."):
                agent = st.session_state.rag_agent
                answer = agent.answer(prompt)
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
    
    st.divider()
    if st.button("🗑️ 清空全部问答记录", use_container_width=False):
        st.session_state.messages = []
        st.success("✅ 全部问答记录已清空")
        st.rerun()

# 3. 历史试卷页面（彻底移除所有测试/重测功能，仅保留查看、导出）
elif st.session_state.page_state == "history_exam":
    st.title("📝 历史试卷中心")
    st.divider()
    
    # 清空全部记录按钮
    if st.session_state.exam_history:
        if st.button("🗑️ 清空全部试题记录", use_container_width=False):
            st.session_state.exam_history = []
            st.session_state.history_current_exam_id = ""
            st.session_state.history_questions = []
            st.session_state.history_q_type = ""
            st.success("✅ 全部试题记录已清空")
            st.rerun()
        st.divider()
    
    # 试卷详情查看（仅查看，无测试）
    if st.session_state.history_current_exam_id:
        current_exam = next(
            (item for item in st.session_state.exam_history if item["id"] == st.session_state.history_current_exam_id),
            None
        )
        if current_exam:
            st.subheader(f"📝 试卷详情 | {current_exam['doc_title']} | {current_exam['q_type']}")
            if st.button("← 返回历史试卷列表", use_container_width=False):
                st.session_state.history_current_exam_id = ""
                st.session_state.history_questions = []
                st.session_state.history_q_type = ""
                st.rerun()
            st.divider()
            
            # 主测试记录查看
            main_test_record = current_exam["main_test_record"]
            if main_test_record:
                st.subheader("📊 测试记录")
                st.metric(
                    label="测试得分",
                    value=f"{main_test_record['total_score']}/100分",
                    delta=f"测试时间：{main_test_record['test_time']}"
                )
                
                col_view, col_export = st.columns([1,1])
                with col_view:
                    if st.button("📋 查看答题详情", use_container_width=True):
                        st.session_state.history_questions = main_test_record["questions"]
                        st.session_state.history_q_type = main_test_record["q_type"]
                        st.session_state.history_user_answers = main_test_record["user_answers"]
                        st.session_state.history_total_score = main_test_record["total_score"]
                        st.session_state.history_score_detail = main_test_record["score_detail"]
                with col_export:
                    if st.button("📤 导出测试结果", use_container_width=True):
                        level = "优秀" if main_test_record['total_score'] >=90 else "良好" if main_test_record['total_score'] >=80 else "中等" if main_test_record['total_score'] >=70 else "及格" if main_test_record['total_score'] >=60 else "不及格"
                        export_text = f"试卷：{current_exam['doc_title']}\n测试时间：{main_test_record['test_time']}\n总分：{main_test_record['total_score']}/100 分\n等级：{level}\n\n详细批改：\n"
                        for detail in main_test_record["score_detail"]:
                            export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                        st.download_button(
                            label="下载结果文件",
                            data=export_text,
                            file_name=f"历史试卷测试结果_{main_test_record['total_score']}分.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
                st.divider()

                # 答题详情展示
                if st.session_state.history_user_answers:
                    st.subheader("📝 答题详情")
                    total_num = len(st.session_state.history_questions)
                    for i in range(total_num):
                        if i not in st.session_state.history_user_answers:
                            continue
                        data = st.session_state.history_user_answers[i]
                        title = data["title"]
                        user_ans = data["user_ans"]
                        correct_ans = data["correct_ans"]
                        analysis = data["analysis"]
                        opts = data.get("opts", [])
                        detail = next((d for d in st.session_state.history_score_detail if d["index"] == i+1), None)
                        
                        with st.container(border=True):
                            st.markdown(f"**Q{i+1}. {title}**")
                            
                            if st.session_state.history_q_type in ["单选", "多选"] and len(opts) == 4:
                                st.markdown(f"A. {opts[0]}")
                                st.markdown(f"B. {opts[1]}")
                                st.markdown(f"C. {opts[2]}")
                                st.markdown(f"D. {opts[3]}")
                                st.markdown("<br>", unsafe_allow_html=True)
                            
                            if detail:
                                st.markdown(f"**本题总分：{detail['total_score']}分 | 你的得分：{detail['get_score']}分**")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                user_display = format_answer(user_ans)
                                st.markdown(f"<p style='color: #ff4444; font-weight: bold;'>你的答案：{user_display}</p>", unsafe_allow_html=True)
                            with col2:
                                st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>正确答案：{correct_ans}</p>", unsafe_allow_html=True)
                            
                            if detail:
                                status = detail["status"]
                                if status == "full":
                                    st.success(f"✅ 回答正确！{detail['remark']}")
                                elif status == "partial":
                                    st.warning(f"⚠️ 部分正确 | {detail['remark']}")
                                else:
                                    st.error(f"❌ 回答错误 | {detail['remark']}")
                            
                            with st.expander("📌 查看详细解析", expanded=False):
                                formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                                st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                st.divider()
            
            # 题目与答案查看
            st.subheader("📌 题目与答案")
            render_view_mode(current_exam["questions"], current_exam["q_type"])
        else:
            st.error("❌ 未找到该试卷，请返回历史试卷列表")
            if st.button("← 返回历史试卷列表"):
                st.session_state.history_current_exam_id = ""
                st.rerun()
    # 试卷列表
    else:
        if not st.session_state.exam_history:
            st.info("暂无试题历史记录，请先生成试题")
        else:
            for idx, item in enumerate(st.session_state.exam_history):
                exam_id = item["id"]
                q_type = item["q_type"]
                doc_title = item["doc_title"]
                create_time = item["time"]
                main_test_record = item["main_test_record"]
                is_tested = main_test_record is not None
                test_tag = "✅ 已测试" if is_tested else "⚠️ 未测试"
                
                panel_title = f"{test_tag} | 试卷 {exam_id} | {q_type} | {doc_title} | {create_time}"
                with st.expander(panel_title, expanded=False):
                    # 删除按钮
                    if st.button(f"❌ 删除本组", key=f"del_exam_{exam_id}"):
                        st.session_state.exam_history.pop(idx)
                        st.success("✅ 本组试题已删除")
                        st.rerun()
                    
                    st.divider()
                    
                    # 查看详情按钮（彻底移除测试按钮）
                    if st.button("📋 查看试卷详情", use_container_width=True, key=f"view_exam_{exam_id}"):
                        st.session_state.history_current_exam_id = exam_id
                        st.session_state.history_questions = item["questions"]
                        st.session_state.history_q_type = item["q_type"]
                        st.session_state.history_user_answers = {}
                        st.session_state.history_total_score = 0
                        st.session_state.history_score_detail = []
                        st.rerun()

# 4. 知识点分析页面（完整保留原有逻辑，调用修改后的knowledge_analysis.py）
elif st.session_state.page_state == "knowledge_analysis":
    render_knowledge_analysis_page()

# 5. 我的错题本页面（唯一保留重测功能的页面，完整实现）
elif st.session_state.page_state == "wrong_book":
    st.title("❌ 我的错题本")
    st.divider()

    wrong_questions = st.session_state.wrong_questions
    # 错题去重（按题干去重，避免重复错题）
    unique_wrongs = []
    seen_titles = set()
    for q in wrong_questions:
        if q["question_title"] not in seen_titles:
            seen_titles.add(q["question_title"])
            unique_wrongs.append(q)
    wrong_questions = unique_wrongs

    # 无错题提示
    if not wrong_questions:
        st.info("🎉 太棒了！你目前没有错题，继续保持~")
    else:
        # 错题统计
        total_wrong = len(wrong_questions)
        knowledge_count = len(set([kp for q in wrong_questions for kp in q["knowledge_points"]]))
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="累计错题数", value=total_wrong)
        with col2:
            st.metric(label="涉及知识点数", value=knowledge_count)
        st.divider()

        # 功能区：错题重测
        st.subheader("📝 错题重测")
        st.caption("勾选需要重新测试的错题，点击「开始重测」即可作答")
        # 错题选择
        selected_ids = []
        with st.container(border=True):
            for idx, q in enumerate(wrong_questions):
                q_id = f"wrong_{idx}"
                kp_text = "、".join(q["knowledge_points"]) if q["knowledge_points"] else "未分类知识点"
                checked = st.checkbox(
                    f"Q{idx+1} | {q['question_title']}（知识点：{kp_text}）",
                    key=q_id,
                    value=True
                )
                if checked:
                    selected_ids.append(idx)
        
        col_start, col_clear = st.columns([1,1])
        with col_start:
            if st.button("🚀 开始重测", use_container_width=True, type="primary"):
                if not selected_ids:
                    st.warning("请至少选择一道错题")
                else:
                    # 生成重测试卷
                    selected_questions = [wrong_questions[i] for i in selected_ids]
                    st.session_state.wrong_questions_for_test = selected_questions
                    st.session_state.wrong_exam_mode = "test"
                    st.session_state.wrong_user_answers = {}
                    st.session_state.wrong_graded = False
                    st.session_state.wrong_total_score = 0
                    st.session_state.wrong_score_detail = []
                    st.rerun()
        with col_clear:
            if st.button("🗑️ 清空全部错题", use_container_width=True):
                st.session_state.user_answer_records = [
                    record for record in st.session_state.user_answer_records
                    if record["is_correct"]
                ]
                st.session_state.wrong_questions = []
                st.success("✅ 全部错题已清空")
                st.rerun()
        st.divider()

        # 错题重测模式
        if st.session_state.wrong_exam_mode == "test":
            st.subheader("📝 错题重测作答")
            test_questions = st.session_state.wrong_questions_for_test
            total_num = len(test_questions)
            q_type = test_questions[0]["question_type"] if test_questions else "单选"

            # 渲染作答界面
            submitted, updated_answers = render_test_mode(
                questions=[q["question_title"] for q in test_questions],
                current_q_type=q_type,
                total_question_num=total_num,
                key_prefix="wrong",
                user_answers=st.session_state.wrong_user_answers
            )
            st.session_state.wrong_user_answers = updated_answers

            # 提交批改
            if submitted:
                total_score, score_detail = grade_exam_answers(
                    user_answers=st.session_state.wrong_user_answers,
                    current_q_type=q_type,
                    total_question_num=total_num,
                    model=st.session_state.model
                )
                st.session_state.wrong_total_score = total_score
                st.session_state.wrong_score_detail = score_detail
                st.session_state.wrong_graded = True
                st.session_state.wrong_exam_mode = "graded"
                st.rerun()

        # 错题重测批改结果
        elif st.session_state.wrong_exam_mode == "graded":
            st.markdown(f"<h2 style='text-align: center;'>📊 重测结果：{st.session_state.wrong_total_score} / 100 分</h2>", unsafe_allow_html=True)
            score = st.session_state.wrong_total_score
            if score >= 90:
                level = "优秀"
                level_color = "#008000"
            elif score >= 80:
                level = "良好"
                level_color = "#32cd32"
            elif score >= 70:
                level = "中等"
                level_color = "#ffd700"
            elif score >= 60:
                level = "及格"
                level_color = "#ffa500"
            else:
                level = "不及格"
                level_color = "#ff4444"
            st.markdown(f"<h3 style='text-align: center; color: {level_color};'>等级：{level}</h3>", unsafe_allow_html=True)
            st.divider()

            # 详细批改
            st.subheader("📝 详细批改")
            test_questions = st.session_state.wrong_questions_for_test
            total_num = len(test_questions)
            q_type = test_questions[0]["question_type"] if test_questions else "单选"

            for i in range(total_num):
                if i not in st.session_state.wrong_user_answers:
                    continue
                data = st.session_state.wrong_user_answers[i]
                title = data["title"]
                user_ans = data["user_ans"]
                correct_ans = data["correct_ans"]
                analysis = data["analysis"]
                opts = data.get("opts", [])
                detail = next((d for d in st.session_state.wrong_score_detail if d["index"] == i+1), None)
                
                with st.container(border=True):
                    st.markdown(f"**Q{i+1}. {title}**")
                    
                    if q_type in ["单选", "多选"] and len(opts) == 4:
                        st.markdown(f"A. {opts[0]}")
                        st.markdown(f"B. {opts[1]}")
                        st.markdown(f"C. {opts[2]}")
                        st.markdown(f"D. {opts[3]}")
                        st.markdown("<br>", unsafe_allow_html=True)
                    
                    if detail:
                        st.markdown(f"**本题总分：{detail['total_score']}分 | 你的得分：{detail['get_score']}分**")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        user_display = format_answer(user_ans)
                        st.markdown(f"<p style='color: #ff4444; font-weight: bold;'>你的答案：{user_display}</p>", unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>正确答案：{correct_ans}</p>", unsafe_allow_html=True)
                    
                    if detail:
                        status = detail["status"]
                        if status == "full":
                            st.success(f"✅ 回答正确！{detail['remark']}")
                        elif status == "partial":
                            st.warning(f"⚠️ 部分正确 | {detail['remark']}")
                        else:
                            st.error(f"❌ 回答错误 | {detail['remark']}")
                    
                    with st.expander("📌 查看详细解析", expanded=False):
                        formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                        st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
            
            st.divider()
            # 重测功能按钮（仅此处保留重新测试）
            col_retest, col_export, col_back = st.columns([1,1,1])
            with col_retest:
                if st.button("🔄 重新测试", use_container_width=True, type="primary"):
                    st.session_state.wrong_exam_mode = "test"
                    st.session_state.wrong_user_answers = {}
                    st.session_state.wrong_graded = False
                    st.session_state.wrong_total_score = 0
                    st.session_state.wrong_score_detail = []
                    st.rerun()
            with col_export:
                if st.button("📤 导出重测结果", use_container_width=True):
                    export_text = f"错题重测结果\n总分：{st.session_state.wrong_total_score}/100 分\n等级：{level}\n\n详细批改：\n"
                    for detail in st.session_state.wrong_score_detail:
                        export_text += f"Q{detail['index']}：总分{detail['total_score']}分，得分{detail['get_score']}分，{detail['remark']}\n"
                    st.download_button(
                        label="下载结果文件",
                        data=export_text,
                        file_name=f"错题重测结果_{st.session_state.wrong_total_score}分.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
            with col_back:
                if st.button("← 返回错题列表", use_container_width=True):
                    st.session_state.wrong_exam_mode = "view"
                    st.session_state.wrong_user_answers = {}
                    st.session_state.wrong_graded = False
                    st.rerun()

        # 错题列表详情（默认查看模式）
        else:
            st.subheader("📋 错题详情列表")
            for idx, q in enumerate(wrong_questions):
                kp_text = "、".join(q["knowledge_points"]) if q["knowledge_points"] else "未分类知识点"
                with st.expander(f"Q{idx+1} | 知识点：{kp_text}", expanded=False):
                    st.markdown(f"**题干：{q['question_title']}**")
                    st.markdown(f"**题型：{q['question_type']}**")
                    st.markdown(f"**你的得分：{q['user_score']}/{q['total_score']}分**")
                    st.markdown(f"**是否答对：❌ 答错**")
                    st.divider()
                    st.markdown("**💡 知识点巩固建议**")
                    st.info(f"本题核心考察「{kp_text}」，建议重新回顾对应知识点的课程内容，结合解析理解考点，再通过重测巩固掌握。")

# 全局底部版权信息
st.divider()
st.caption("💡 NLP智能题库系统 | 基于Sentence-BERT语义匹配 | 在线作答 | 精准评分 | 自动批改")
