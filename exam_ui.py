import streamlit as st
from exam_core import clean_option_prefix, format_answer

def init_session_state():
    """初始化会话状态，避免KeyError"""
    if "user_answers" not in st.session_state:
        st.session_state.user_answers = {}
    if "graded" not in st.session_state:
        st.session_state.graded = False
    if "total_score" not in st.session_state:
        st.session_state.total_score = 0.0
    if "score_detail" not in st.session_state:
        st.session_state.score_detail = []
    if "user_answer_records" not in st.session_state:
        st.session_state.user_answer_records = []

def render_view_mode(questions: list, current_q_type: str):
    """渲染【查看答案模式】的UI"""
    init_session_state()
    for i, line in enumerate(questions):
        if current_q_type in ["单选", "多选"]:
            parts = line.split("###")
            if len(parts) >= 7:
                title, opt_a, opt_b, opt_c, opt_d, ans, analysis = parts[:7]
                opt_a_clean = clean_option_prefix(opt_a)
                opt_b_clean = clean_option_prefix(opt_b)
                opt_c_clean = clean_option_prefix(opt_c)
                opt_d_clean = clean_option_prefix(opt_d)
                
                with st.container(border=True):
                    st.markdown(f"**Q{i+1}. {title}**")
                    st.markdown(f"A. {opt_a_clean}")
                    st.markdown(f"B. {opt_b_clean}")
                    st.markdown(f"C. {opt_c_clean}")
                    st.markdown(f"D. {opt_d_clean}")
                    
                    with st.expander("📌 查看答案 & 详细解析", expanded=False):
                        st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>正确答案：{ans}</p>", unsafe_allow_html=True)
                        formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                        st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
        
        elif current_q_type == "判断":
            parts = line.split("###")
            if len(parts) >= 3:
                title, ans, analysis = parts[:3]
                with st.container(border=True):
                    st.markdown(f"**Q{i+1}. {title}**")
                    with st.expander("📌 查看答案 & 详细解析", expanded=False):
                        st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>答案：{ans}</p>", unsafe_allow_html=True)
                        formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                        st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
        
        elif current_q_type == "简答":
            parts = line.split("###")
            if len(parts) >= 3:
                title, ref_ans, analysis = parts[:3]
                with st.container(border=True):
                    st.markdown(f"**Q{i+1}. {title}**")
                    with st.expander("📌 查看参考答案 & 详细解析", expanded=False):
                        st.markdown(f"<p style='color: #0066cc; font-weight: bold;'>参考答案：{ref_ans}</p>", unsafe_allow_html=True)
                        formatted_analysis = analysis.replace('<br>', '\n').replace('\n', '<br>')
                        st.markdown(f"<p style='color: #008000;'><strong>详细解析：</strong><br>{formatted_analysis}</p>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)

def render_test_mode(
    questions: list, 
    current_q_type: str, 
    total_question_num: int,
    key_prefix: str = "main",
    user_answers: dict = None
) -> tuple[bool, dict]:
    """
    渲染【在线测试模式】的表单UI
    :param questions: 题目列表
    :param current_q_type: 题型
    :param total_question_num: 总题数
    :param key_prefix: 组件key前缀，避免不同试卷的key冲突
    :param user_answers: 存储用户答案的字典
    :return: 是否提交批改, 更新后的用户答案字典
    """
    init_session_state()
    if user_answers is None:
        user_answers = {}
    
    if len(user_answers) != total_question_num:
        user_answers = {}
    
    submitted = False
    with st.form(f"exam_form_{key_prefix}", clear_on_submit=False):
        unanswered_warning = st.empty()
        
        for i, line in enumerate(questions):
            if current_q_type == "单选":
                parts = line.split("###")
                if len(parts) >= 7:
                    title, opt_a, opt_b, opt_c, opt_d, ans, analysis = parts[:7]
                    opt_a_clean = clean_option_prefix(opt_a)
                    opt_b_clean = clean_option_prefix(opt_b)
                    opt_c_clean = clean_option_prefix(opt_c)
                    opt_d_clean = clean_option_prefix(opt_d)
                    
                    options_list = [
                        f"A. {opt_a_clean}",
                        f"B. {opt_b_clean}",
                        f"C. {opt_c_clean}",
                        f"D. {opt_d_clean}"
                    ]
                    
                    with st.container(border=True):
                        user_ans_raw = st.radio(
                            f"Q{i+1}. {title}",
                            options=options_list,
                            key=f"{key_prefix}_q_{i}",
                            index=None,
                            label_visibility="visible"
                        )
                        user_ans = user_ans_raw.split(".")[0].strip() if user_ans_raw else None
                        user_answers[i] = {
                            "user_ans": user_ans,
                            "correct_ans": ans,
                            "analysis": analysis,
                            "title": title,
                            "opts": [opt_a_clean, opt_b_clean, opt_c_clean, opt_d_clean]
                        }
            
            elif current_q_type == "多选":
                parts = line.split("###")
                if len(parts) >= 7:
                    title, opt_a, opt_b, opt_c, opt_d, ans, analysis = parts[:7]
                    opt_a_clean = clean_option_prefix(opt_a)
                    opt_b_clean = clean_option_prefix(opt_b)
                    opt_c_clean = clean_option_prefix(opt_c)
                    opt_d_clean = clean_option_prefix(opt_d)
                    
                    option_config = [
                        ("A", opt_a_clean),
                        ("B", opt_b_clean),
                        ("C", opt_c_clean),
                        ("D", opt_d_clean)
                    ]
                    
                    with st.container(border=True):
                        st.markdown(f"**Q{i+1}. {title}**")
                        selected_list = []
                        for opt_letter, opt_text in option_config:
                            is_selected = st.checkbox(
                                f"{opt_letter}. {opt_text}",
                                key=f"{key_prefix}_q_{i}_opt_{opt_letter}",
                                value=False
                            )
                            if is_selected:
                                selected_list.append(opt_letter)
                        
                        selected_list_sorted = sorted(selected_list)
                        correct_ans_sorted = sorted(list(ans.strip())) if ans else []
                        user_answers[i] = {
                            "user_ans": selected_list,
                            "correct_ans": ans,
                            "correct_ans_sorted": correct_ans_sorted,
                            "analysis": analysis,
                            "title": title,
                            "opts": [opt_a_clean, opt_b_clean, opt_c_clean, opt_d_clean]
                        }
            
            elif current_q_type == "判断":
                parts = line.split("###")
                if len(parts) >= 3:
                    title, ans, analysis = parts[:3]
                    with st.container(border=True):
                        user_ans = st.radio(
                            f"Q{i+1}. {title}",
                            ["正确", "错误"],
                            key=f"{key_prefix}_q_{i}",
                            index=None,
                            label_visibility="visible"
                        )
                        user_answers[i] = {
                            "user_ans": user_ans,
                            "correct_ans": ans,
                            "analysis": analysis,
                            "title": title
                        }
            
            elif current_q_type == "简答":
                parts = line.split("###")
                if len(parts) >= 3:
                    title, ref_ans, analysis = parts[:3]
                    with st.container(border=True):
                        st.markdown(f"**Q{i+1}. {title}**")
                        user_ans = st.text_area(
                            f"请输入你的答案：",
                            key=f"{key_prefix}_q_{i}",
                            height=100,
                            label_visibility="collapsed",
                            placeholder="请在此输入你的答案，尽可能详细作答..."
                        )
                        user_answers[i] = {
                            "user_ans": user_ans.strip() if user_ans else "",
                            "correct_ans": ref_ans,
                            "analysis": analysis,
                            "title": title
                        }
            
            st.markdown("<br>", unsafe_allow_html=True)
        
        submitted = st.form_submit_button("✅ 提交答案并批改", use_container_width=True, type="primary")
        
        if submitted:
            unanswered = [i+1 for i in range(total_question_num) if i not in user_answers or user_answers[i]["user_ans"] in [None, [], ""]]
            if unanswered:
                unanswered_warning.warning(f"⚠️ 发现未作答题目：{unanswered}，请完成所有题目后再提交！")
                submitted = False
    
    return submitted, user_answers

def render_graded_results(
    questions: list, 
    current_q_type: str, 
    total_question_num: int,
    user_answers: dict,
    score_detail: list,
    total_score: float,
    key_prefix: str = "main"
) -> tuple[bool, bool]:
    """
    渲染【批改后结果】的UI
    :param questions: 题目列表
    :param current_q_type: 题型
    :param total_question_num: 总题数
    :param user_answers: 用户答案字典
    :param score_detail: 得分详情
    :param total_score: 总分
    :param key_prefix: 组件key前缀
    :return: 是否重新测试, 是否导出结果
    """
    init_session_state()
    st.markdown(f'<a name="graded_results_{key_prefix}"></a>', unsafe_allow_html=True)
    st.divider()
    st.markdown(f"<h2 style='text-align: center; color: #0066cc;'>📊 测试结果：{total_score} / 100 分</h2>", unsafe_allow_html=True)
    
    score = total_score
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
    
    st.subheader("📝 详细批改")
    for i in range(total_question_num):
        if i not in user_answers:
            continue
        data = user_answers[i]
        title = data["title"]
        user_ans = data["user_ans"]
        correct_ans = data["correct_ans"]
        analysis = data["analysis"]
        opts = data.get("opts", [])
        detail = next((d for d in score_detail if d["index"] == i+1), None)
        
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
    
    col_reset, col_export = st.columns(2)
    reset_clicked = False
    export_clicked = False
    with col_reset:
        if st.button("🔄 重新测试", use_container_width=True, type="secondary", key=f"{key_prefix}_reset"):
            reset_clicked = True
    with col_export:
        if st.button("📤 导出测试结果", use_container_width=True, type="secondary", key=f"{key_prefix}_export"):
            export_clicked = True
    
    return reset_clicked, export_clicked