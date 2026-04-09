# knowledge_analysis.py 知识点掌握度分析核心模块
import re
import jieba
from collections import defaultdict
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ==================== 1. 知识点提取配置（完全保留原有内容） ====================
# 马原高频知识点词根，用于精准匹配（你可以根据你的题库补充）
KNOWLEDGE_ROOT_WORDS = {
    "实践与认识", "实践", "认识", "真理", "价值", "感性认识", "理性认识",
    "唯物论", "物质", "意识", "能动作用", "人工智能", "客观规律",
    "辩证法", "矛盾", "对立统一", "质量互变", "否定之否定", "联系", "发展",
    "唯物史观", "社会存在", "社会意识", "生产力", "生产关系", "经济基础", "上层建筑",
    "政治经济学", "商品", "价值", "剩余价值", "资本", "资本主义", "经济危机", "基本矛盾",
    "劳动二重性", "剩余价值规律", "资本积累", "资本循环", "资本周转"
}
# 掌握度等级划分标准
MASTERY_LEVEL = {
    "master": {"name": "完全掌握", "min_rate": 0.85, "color": "#00a86b"},
    "familiar": {"name": "熟悉", "min_rate": 0.6, "color": "#1e88e5"},
    "weak": {"name": "薄弱", "min_rate": 0.3, "color": "#ff9800"},
    "strange": {"name": "陌生", "min_rate": 0, "color": "#f44336"}
}

# ==================== 2. 知识点提取函数（完全保留原有内容） ====================
def extract_knowledge_points(question: str, analysis: str) -> list:
    """
    从题干和题目解析中提取知识点标签
    :param question: 题干内容
    :param analysis: 题目详细解析
    :return: 知识点标签列表
    """
    full_text = f"{question} {analysis}"
    full_text_clean = full_text.replace('<br>', '').replace('&nbsp;', '').replace('\n', '')
    
    # 1. 优先匹配高频知识点词根
    matched_points = []
    for root_word in KNOWLEDGE_ROOT_WORDS:
        if root_word in full_text_clean:
            matched_points.append(root_word)
    
    # 2. 从解析的【答案依据】【答题框架】里补充知识点
    frame_pattern = re.compile(r'【答题满分框架拆解】([\s\S]*?)(?=【|$)')
    frame_match = frame_pattern.search(full_text_clean)
    if frame_match:
        frame_content = frame_match.group(1)
        point_pattern = re.compile(r'[①②③④⑤⑥⑦⑧⑨⑩]\s*([^()]+?)\s*\(\d+分\)')
        frame_points = point_pattern.findall(frame_content)
        for p in frame_points:
            p_clean = p.strip()
            if p_clean and p_clean not in matched_points and len(p_clean) < 20:
                matched_points.append(p_clean)
    
    # 去重+兜底
    matched_points = list(dict.fromkeys(matched_points))
    if not matched_points:
        matched_points = ["综合知识点"]
    return matched_points

# ==================== 3. 掌握度计算函数（完全保留原有内容） ====================
def calc_knowledge_mastery(answer_records: list) -> pd.DataFrame:
    """
    根据答题记录计算每个知识点的掌握度
    :param answer_records: 答题记录列表
    :return: 知识点掌握度DataFrame
    """
    # 按知识点累加得分
    knowledge_total_score = defaultdict(float)  # 知识点对应题目的总分
    knowledge_user_score = defaultdict(float)   # 用户在该知识点的总得分
    knowledge_question_count = defaultdict(int) # 该知识点的题目数量
    for record in answer_records:
        points = record.get("knowledge_points", ["综合知识点"])
        total_score = record.get("total_score", 0)
        user_score = record.get("user_score", 0)
        
        # 把题目分数平均分配给每个知识点
        per_point_total = total_score / len(points)
        per_point_user = user_score / len(points)
        
        for point in points:
            knowledge_total_score[point] += per_point_total
            knowledge_user_score[point] += per_point_user
            knowledge_question_count[point] += 1
    
    # 生成掌握度数据
    mastery_data = []
    for point in knowledge_total_score.keys():
        total = knowledge_total_score[point]
        user = knowledge_user_score[point]
        correct_rate = user / total if total > 0 else 0
        question_count = knowledge_question_count[point]
        
        # 判定掌握度等级
        level = "strange"
        for level_key, level_config in MASTERY_LEVEL.items():
            if correct_rate >= level_config["min_rate"]:
                level = level_key
                break
        
        mastery_data.append({
            "知识点": point,
            "题目数量": question_count,
            "总满分": round(total, 2),
            "用户得分": round(user, 2),
            "正确率": round(correct_rate * 100, 2),
            "掌握度等级": MASTERY_LEVEL[level]["name"],
            "等级颜色": MASTERY_LEVEL[level]["color"],
            "掌握度系数": round(correct_rate, 2)
        })
    
    # 转DataFrame并按正确率排序
    df = pd.DataFrame(mastery_data).sort_values(by="正确率", ascending=False)
    return df

# ==================== 4. 【核心修改】可视化图表生成（替换为你需要的两个模块） ====================
def render_mastery_chart(mastery_df: pd.DataFrame):
    """
    渲染可视化图表：
    1. 成绩变化趋势折线图
    2. 知识点掌握率柱状图
    """
    # ========== 模块1：成绩变化趋势折线图 ==========
    st.subheader("📈 成绩变化趋势")
    # 提取所有测试记录
    all_test_records = []
    for exam in st.session_state.get("exam_history", []):
        # 主界面测试记录
        if exam.get("main_test_record"):
            record = exam["main_test_record"]
            all_test_records.append({
                "time": record["test_time"],
                "score": record["total_score"],
                "exam_name": exam["doc_title"]
            })
        # 历史练习记录
        for practice in exam.get("practice_records", []):
            all_test_records.append({
                "time": practice["test_time"],
                "score": practice["total_score"],
                "exam_name": exam["doc_title"]
            })
    
    # 按测试时间升序排序
    all_test_records.sort(key=lambda x: datetime.strptime(x["time"], "%Y-%m-%d %H:%M:%S"))
    
    if all_test_records:
        time_list = [x["time"] for x in all_test_records]
        score_list = [x["score"] for x in all_test_records]
        
        # 生成折线图（原生主题适配，无硬编码深色样式）
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=time_list,
            y=score_list,
            mode='lines+markers',
            name='测试成绩',
            line=dict(width=3),
            marker=dict(size=6)
        ))
        
        # 图表基础配置（适配系统主题）
        fig_trend.update_layout(
            xaxis_title="测试时间",
            yaxis_title="得分（满分100）",
            yaxis_range=[0, 100],
            height=400,
            hovermode="x unified"
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("暂无测试成绩记录，完成测试后即可查看成绩变化趋势")

    st.divider()

    # ========== 模块2：知识点掌握率柱状图 ==========
    st.subheader("🎯 知识点掌握率")
    if not mastery_df.empty:
        # 生成柱状图，hover显示详情，适配原生主题
        fig_bar = px.bar(
            mastery_df,
            x="知识点",
            y="正确率",
            color="掌握度等级",
            color_discrete_map={v["name"]: v["color"] for v in MASTERY_LEVEL.values()},
            text_auto='.2f',
            range_y=[0, 100],
            hover_data={
                "知识点": True,
                "正确率": ":,.2f%",
                "题目数量": True,
                "掌握度等级": True
            }
        )
        # 图表基础配置
        fig_bar.update_layout(
            xaxis_title="知识点",
            yaxis_title="掌握率（%）",
            height=500
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("暂无知识点数据，完成测试后即可查看知识点掌握率")

# ==================== 5. 复习建议生成（完全保留原有内容） ====================
def generate_review_suggestion(mastery_df: pd.DataFrame) -> str:
    """根据掌握度生成针对性复习建议"""
    weak_points = mastery_df[mastery_df["掌握度等级"].isin(["薄弱", "陌生"])]["知识点"].tolist()
    familiar_points = mastery_df[mastery_df["掌握度等级"] == "熟悉"]["知识点"].tolist()
    master_points = mastery_df[mastery_df["掌握度等级"] == "完全掌握"]["知识点"].tolist()
    suggestion = "### 📝 针对性复习建议\n"
    if weak_points:
        suggestion += f"#### 🔴 重点突破（薄弱/陌生知识点）\n"
        suggestion += f"你在 **{', '.join(weak_points)}** 这些知识点的掌握度不足，建议：\n"
        suggestion += "1. 重新回归教材，梳理该知识点的核心原理和逻辑框架\n"
        suggestion += "2. 针对性刷该知识点的基础题，先吃透核心概念，再做综合题\n"
        suggestion += "3. 整理该知识点的错题，总结错误原因，避免重复踩坑\n\n"
    
    if familiar_points:
        suggestion += f"#### 🟡 巩固提升（熟悉知识点）\n"
        suggestion += f"你对 **{', '.join(familiar_points)}** 已经有基础掌握，建议：\n"
        suggestion += "1. 多做该知识点的综合应用题和变形题，提升灵活运用能力\n"
        suggestion += "2. 梳理该知识点和其他知识点的关联，构建完整的知识体系\n\n"
    
    if master_points:
        suggestion += f"#### 🟢 保持优势（完全掌握知识点）\n"
        suggestion += f"你已经完全掌握 **{', '.join(master_points)}**，建议：\n"
        suggestion += "1. 定期做少量该知识点的题，保持手感，避免遗忘\n"
        suggestion += "2. 可以挑战该知识点的难题、压轴题，进一步拔高能力\n"
    
    if len(weak_points) == 0 and len(familiar_points) == 0:
        suggestion = "🎉 恭喜！你已经完全掌握了所有知识点，继续保持定期刷题巩固即可！"
    
    return suggestion

# ==================== 6. 页面渲染主函数（完全保留原有内容，仅调整可视化调用） ====================
def render_knowledge_analysis_page():
    """渲染知识点分析页面"""
    st.title("📚 知识点掌握度分析")
    # 从session_state获取答题记录
    answer_records = st.session_state.get("user_answer_records", [])
    if not answer_records:
        st.warning("你还没有完成任何题目，快去答题后再来查看分析吧！")
        return
    
    # 计算掌握度
    mastery_df = calc_knowledge_mastery(answer_records)

    # ========== 1. 答题数据概览（完全保留原有内容，和截图完全匹配） ==========
    st.subheader("📋 答题数据概览")
    col1, col2, col3, col4 = st.columns(4)
    total_questions = len(answer_records)
    total_score = sum([r.get("total_score", 0) for r in answer_records])
    user_total_score = sum([r.get("user_score", 0) for r in answer_records])
    total_correct_rate = user_total_score / total_score * 100 if total_score > 0 else 0
    with col1:
        st.metric("累计答题数", total_questions)
    with col2:
        st.metric("累计总分", round(total_score, 2))
    with col3:
        st.metric("你的总得分", round(user_total_score, 2))
    with col4:
        st.metric("整体正确率", f"{round(total_correct_rate, 2)}%")
    
    st.divider()

    # ========== 2. 可视化图表（调用修改后的新模块） ==========
    render_mastery_chart(mastery_df)
    st.divider()

    # ========== 3. 知识点掌握度详情表格（完全保留原有内容） ==========
    st.subheader("📑 知识点掌握度详情")
    st.dataframe(
        mastery_df[["知识点", "题目数量", "正确率", "掌握度等级"]],
        use_container_width=True,
        hide_index=True
    )
    st.divider()

    # ========== 4. 复习建议（完全保留原有内容） ==========
    st.markdown(generate_review_suggestion(mastery_df))

    # ========== 5. 清空记录按钮（完全保留原有内容） ==========
    st.divider()
    if st.button("🗑️ 清空答题记录", type="secondary"):
        st.session_state.user_answer_records = []
        st.success("答题记录已清空！")
        st.rerun()