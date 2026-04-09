import re
import jieba
from typing import List, Dict, Tuple, Optional

def clean_option_prefix(option_text: str) -> str:
    """清洗选项开头重复的A. B. C. D. 前缀"""
    option_text = option_text.strip()
    prefix_pattern = re.compile(r'^[A-Da-d][\.、\)\s]*')
    return prefix_pattern.sub('', option_text).strip()

def format_answer(ans):
    """格式化答案显示，把列表转成顿号分隔的字符串"""
    if isinstance(ans, list):
        return "、".join(ans) if ans else "未作答"
    return ans if ans else "未作答"

def get_multiple_choice_score(user_ans: list, correct_ans: str, total_score: float) -> Tuple[float, str, str]:
    """
    多选题评分规则：
    1. 选了错误选项 → 0分，状态wrong
    2. 没选错，但没选全正确选项 → 按选对数量给分，状态partial（部分正确）
    3. 没选错，全选对正确选项 → 满分，状态full（全对）
    返回：本题得分、评分说明、状态（wrong/partial/full）
    """
    correct_opts = list(correct_ans.strip().upper())
    correct_opt_count = len(correct_opts)
    if correct_opt_count == 0:
        return 0, "正确答案异常", "wrong"
    
    per_opt_score = total_score / correct_opt_count
    user_opts = [x.upper() for x in user_ans]
    has_wrong_opt = any(opt not in correct_opts for opt in user_opts)
    
    if has_wrong_opt:
        return 0, "选了错误选项，本题得0分", "wrong"
    else:
        correct_count = len([opt for opt in user_opts if opt in correct_opts])
        final_score = correct_count * per_opt_score
        if correct_count == correct_opt_count:
            return round(final_score, 2), f"选对全部{correct_count}个正确选项，本题得满分", "full"
        else:
            return round(final_score, 2), f"选对{correct_count}/{correct_opt_count}个正确选项，本题得{round(final_score, 2)}分", "partial"

# ==================== 通用中文停用词表 ====================
STOP_WORDS = {
    "的", "了", "在", "是", "就", "都", "而", "及", "与", "和", "也", "关键", "在于", "核心",
    "主要", "什么", "？", "。", "，", "：", "；", "、", "（", "）", "《", "》", "！", "!", "?", ".",
    "我们", "你", "我", "它", "他", "她", "这", "那", "此", "彼", "之", "以", "为", "有", "无", "不",
    "会", "能", "可以", "应当", "必须", "如果", "但是", "然而", "因此", "所以", "因为", "由于", "从而",
    "体现", "表现", "说明", "分析", "阐述", "论述", "指出", "表明", "认为", "包括", "以及", "及其", "具有",
    "本题", "满分", "分", "答题", "如下", "必须", "逻辑", "体现", "深度", "考点", "考情",
    "答案", "依据", "综合", "文档", "多个", "知识点", "核心", "表述", "避坑", "指南",
    "延伸", "拓展", "常见", "失分点", "混淆", "等同于", "忽视", "缺乏", "导致",
    "原理", "随着", "技术", "发展", "关于", "是否", "具有", "讨论", "日益", "深入",
    "既是", "检验", "也是", "丰富", "发展", "阅卷", "标准", "从", "上升", "到", "高度",
    "本质", "特征", "独特", "意义", "分析", "定义", "应用", "特征", "体现", "表现",
    "就是", "这个", "那个", "这样", "那样", "通过", "比如", "例如", "如", "就是"
}

def get_short_answer_score(
    user_ans: str, 
    correct_ans: str,
    analysis: str, 
    total_score: float,
    model: Optional[object] = None
) -> Tuple[float, int, str, List[Dict]]:
    """简答题智能评分"""
    analysis_clean = analysis.replace('<br>', '\n').replace('<br/>', '\n').replace('&nbsp;', ' ')
    analysis_clean = re.sub(r'[ \t]+', ' ', analysis_clean)
    analysis_clean = analysis_clean.replace('：', ':').replace('；', ';').replace('（', '(').replace('）', ')')
    score_points = []
    depth_content = ""
    depth_sentences = []
    depth_pattern = re.compile(r'【知识点深度原理分析】([\s\S]*?)(?=【|$)')
    depth_match = depth_pattern.search(analysis_clean)
    if depth_match:
        depth_content = depth_match.group(1).strip()
        depth_sentences_raw = re.split(r'[。！？;；]\s*', depth_content)
        depth_sentences = [
            {"text": s.strip(), "used": False} 
            for s in depth_sentences_raw 
            if len(s.strip()) >= 10
        ]
    frame_pattern = re.compile(r'【答题满分框架拆解】([\s\S]*?)(?=【|$)')
    frame_match = frame_pattern.search(analysis_clean)
    if frame_match:
        frame_content = frame_match.group(1).strip()
        point_pattern = re.compile(r'([①②③④⑤⑥⑦⑧⑨⑩]|\d+\.|\(\d+\))\s*([^()]+?)\s*\(\d+分\)')
        frame_points_raw = point_pattern.findall(frame_content)
        if frame_points_raw:
            frame_titles = list(dict.fromkeys([p[1].strip() for p in frame_points_raw]))
            for title in frame_titles:
                title_words = jieba.lcut(title)
                title_core_words = set([w for w in title_words if w not in STOP_WORDS and len(w)>=2])
                best_sentence = ""
                best_sentence_idx = -1
                max_match = 0
                for idx, sent_info in enumerate(depth_sentences):
                    if sent_info["used"]:
                        continue
                    sent_clean = sent_info["text"]
                    sent_words = jieba.lcut(sent_clean)
                    sent_core_words = set([w for w in sent_words if w not in STOP_WORDS and len(w)>=2])
                    match_count = len(title_core_words & sent_core_words)
                    if match_count > max_match:
                        max_match = match_count
                        best_sentence = sent_clean
                        best_sentence_idx = idx
                
                if best_sentence and max_match >= 1 and best_sentence_idx != -1:
                    depth_sentences[best_sentence_idx]["used"] = True
                    score_points.append(best_sentence)
                else:
                    score_points.append(title)
    
    if not score_points and depth_content:
        point_pattern = re.compile(r'([①②③④⑤⑥⑦⑧⑨⑩]|\d+\.|\(\d+\))\s*([^;;\n]+?[。！？;；]?)')
        raw_points = point_pattern.findall(depth_content)
        valid_points = list(dict.fromkeys([p[1].strip() for p in raw_points if len(p[1].strip()) >= 10]))
        if valid_points:
            score_points = valid_points
    
    if not score_points:
        old_pattern = re.compile(r'得分点\d+[:：]\s*([^;;\n<]+)')
        old_points = old_pattern.findall(analysis_clean)
        valid_old_points = list(dict.fromkeys([p.strip() for p in old_points if len(p.strip()) >= 8]))
        if valid_old_points:
            score_points = valid_old_points
    
    point_count = len(score_points)
    if point_count == 0:
        ref_points = re.split(r'[。！？;；]\s*', correct_ans.strip())
        valid_ref_points = list(dict.fromkeys([p.strip() for p in ref_points if len(p.strip()) >= 8]))
        score_points = valid_ref_points if valid_ref_points else [correct_ans.strip()]
    score_points = list(dict.fromkeys(score_points))
    point_count = len(score_points)
    
    per_point_score = total_score / point_count
    hit_count = 0
    hit_detail = []
    SIMILARITY_THRESHOLD = 65
    KEYWORD_THRESHOLD = 0.45
    
    user_ans_clean = user_ans.strip()
    user_words = jieba.lcut(user_ans_clean)
    user_core_words = set([word for word in user_words if word.strip() and word not in STOP_WORDS])
    
    for idx, point in enumerate(score_points):
        point_clean = point.strip()
        is_hit = False
        similarity = 0
        mode_used = "关键词匹配"
        
        if model is not None:
            try:
                from sentence_transformers import util
                user_embedding = model.encode(user_ans_clean, convert_to_tensor=True, normalize_embeddings=True)
                point_embedding = model.encode(point_clean, convert_to_tensor=True, normalize_embeddings=True)
                similarity = util.cos_sim(user_embedding, point_embedding).item() * 100
                is_hit = similarity >= SIMILARITY_THRESHOLD
                mode_used = "语义匹配"
            except Exception as e:
                print(f"语义匹配失败，降级关键词匹配：{str(e)}")
        
        if not is_hit:
            point_words = jieba.lcut(point_clean)
            point_core_words = set([word for word in point_words if word.strip() and word not in STOP_WORDS])
            
            if point_core_words:
                hit_words = user_core_words & point_core_words
                hit_ratio = len(hit_words) / len(point_core_words)
                similarity = hit_ratio * 100
                is_hit = hit_ratio >= KEYWORD_THRESHOLD
        
        if is_hit:
            hit_count += 1
        
        hit_detail.append({
            "score_point": point_clean,
            "similarity": round(similarity, 2),
            "is_hit": is_hit,
            "mode": mode_used
        })
    
    final_score = round(hit_count * per_point_score, 2)
    remark = f"命中{hit_count}/{point_count}个采分点，本题得{final_score}分"
    
    return final_score, point_count, remark, hit_detail

# ==================== 【新增】全卷批改核心函数 ====================
def grade_exam_answers(
    user_answers: dict,
    current_q_type: str,
    total_question_num: int,
    model: object = None
) -> tuple[float, list]:
    """
    批改用户的答题答案，返回总分和得分详情
    :param user_answers: 用户答案字典
    :param current_q_type: 题型
    :param total_question_num: 总题数
    :param model: SBERT模型，用于简答题评分
    :return: 总分, 得分详情列表
    """
    total_score = 0
    score_detail = []
    per_question_base_score = 100 / total_question_num if total_question_num > 0 else 0
    
    for i in range(total_question_num):
        if i not in user_answers:
            score_detail.append({
                "index": i+1,
                "total_score": round(per_question_base_score, 2),
                "get_score": 0,
                "is_correct": False,
                "is_partial": False,
                "remark": "未作答",
                "status": "wrong",
                "hit_detail": []
            })
            continue
        
        data = user_answers[i]
        user_ans = data["user_ans"]
        correct_ans = data["correct_ans"]
        analysis = data["analysis"]
        question_total_score = per_question_base_score
        get_score = 0
        is_correct = False
        is_partial = False
        remark = ""
        status = "wrong"
        hit_detail = []
        
        if current_q_type == "单选":
            if str(user_ans).strip().upper() == str(correct_ans).strip().upper():
                get_score = question_total_score
                is_correct = True
                remark = "回答正确，得满分"
                status = "full"
            else:
                get_score = 0
                remark = f"回答错误，正确答案是{correct_ans}"
                status = "wrong"
        
        elif current_q_type == "判断":
            if str(user_ans).strip() == str(correct_ans).strip():
                get_score = question_total_score
                is_correct = True
                remark = "回答正确，得满分"
                status = "full"
            else:
                get_score = 0
                remark = f"回答错误，正确答案是{correct_ans}"
                status = "wrong"
        
        elif current_q_type == "多选":
            get_score, remark, status = get_multiple_choice_score(
                user_ans, 
                correct_ans, 
                question_total_score
            )
            is_correct = status == "full"
            is_partial = status == "partial"
        
        elif current_q_type == "简答":
            if not model:
                get_score = 0
                remark = "NLP评分模型未加载，无法评分"
                status = "wrong"
            else:
                get_score, point_count, remark, hit_detail = get_short_answer_score(
                    user_ans, 
                    correct_ans,
                    analysis, 
                    question_total_score, 
                    model
                )
                is_correct = get_score >= question_total_score * 0.99
                status = "full" if is_correct else "wrong"
        
        total_score += get_score
        score_detail.append({
            "index": i+1,
            "total_score": round(question_total_score, 2),
            "get_score": round(get_score, 2),
            "is_correct": is_correct,
            "is_partial": is_partial,
            "remark": remark,
            "status": status,
            "hit_detail": hit_detail,
            "title": data["title"],
            "analysis": analysis
        })
    
    return round(total_score, 2), score_detail