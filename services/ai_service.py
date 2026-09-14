import json
import logging

import dashscope

from config import Config

logger = logging.getLogger(__name__)

dashscope.api_key = Config.DASHSCOPE_API_KEY


def grade_short_answer_ai(question_text, standard_answer_hint, student_answer):
    prompt = f"""
    你是一位严谨的考试阅卷官。请根据【标准得分点】，对【学生答案】进行评分。
    评分规则：
    1. 满分 10 分。
    2. 请根据语义相似度打分，不要因为措辞不同而扣分。
    3. 如果学生没答，或者答非所问，给 0 分。

    请严格按照 JSON 格式输出，不要输出任何其他解释：
    {{"score": 8, "comment": "答案基本正确，涵盖了主要得分点"}}

    【题目】
    {question_text}

    【标准得分点】
    {standard_answer_hint}

    【学生答案】
    {student_answer}
    """

    try:
        response = dashscope.Generation.call(model='qwen-max', prompt=prompt)
        result_text = response.output.text.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 2)[2].rstrip("`")

        result = json.loads(result_text)
        ai_score = int(result['score'])
        ai_comment = result['comment']
        return ai_score, ai_comment

    except Exception as e:
        logger.error(f"AI 评分出错: {e}")
        return None, "AI 评分系统暂时繁忙，请人工复核"


def ai_generate_questions(topic, difficulty, num, question_type):
    type_names = {
        'multiple_choice': '单选题',
        'multiple_select': '多选题',
        'true_false': '判断题',
        'short_answer': '简答题',
        'programming': '编程题'
    }
    type_name = type_names.get(question_type, '单选题')

    prompts = {
        'multiple_choice': f"""
            你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的单选题。
            请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记，不要包含任何解释性文字：
            [
                {{
                    "question_text": "题目内容",
                    "option_a": "选项A内容",
                    "option_b": "选项B内容",
                    "option_c": "选项C内容",
                    "option_d": "选项D内容",
                    "correct_answer": "A",
                    "explanation": "详细解析，包括正确答案分析、错误选项分析和知识点补充"
                }}
            ]
            """,
        'multiple_select': f"""
            你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的多选题（有多个正确答案）。
            请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记，不要包含任何解释性文字：
            [
                {{
                    "question_text": "题目内容",
                    "option_a": "选项A内容",
                    "option_b": "选项B内容",
                    "option_c": "选项C内容",
                    "option_d": "选项D内容",
                    "option_e": "选项E内容（如果没有E选项则留空）",
                    "option_f": "选项F内容（如果没有F选项则留空）",
                    "correct_answer": "A,B,C",
                    "explanation": "详细解析，包括各选项对错分析和知识点补充"
                }}
            ]
            """,
        'true_false': f"""
            你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的判断题。
            请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记，不要包含任何解释性文字：
            [
                {{
                    "question_text": "判断题题目内容（陈述一个观点或事实）",
                    "correct_answer": "A",
                    "explanation": "详细解析，说明为什么该陈述正确或错误，以及相关知识点"
                }}
            ]
            注意：correct_answer 只能是 "A"（正确）或 "B"（错误）。
            """,
        'short_answer': f"""
            你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的简答题。
            请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记，不要包含任何解释性文字：
            [
                {{
                    "question_text": "简答题题目内容",
                    "correct_answer": "参考答案（详细的标准答案，包含得分要点）",
                    "explanation": "答题思路分析、得分要点说明和相关知识点补充"
                }}
            ]
            """,
        'programming': f"""
            你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的Python编程题。
            请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记，不要包含任何解释性文字：
            [
                {{
                    "question_text": "编程题题目描述，包括功能要求和输入输出说明",
                    "test_cases": "[{{\\"input\\": \\"输入数据\\", \\"expected_output\\": \\"期望输出\\"}}]",
                    "solution_code": "def solution():\\n    # 参考答案代码\\n    pass",
                    "correct_answer": "参考答案代码",
                    "explanation": "解题思路、算法分析、代码要点和易错点"
                }}
            ]
            注意：test_cases 是一个 JSON 数组字符串，每个元素包含 input 和 expected_output。
            """
    }

    prompt = prompts.get(question_type, prompts['multiple_choice'])

    try:
        response = dashscope.Generation.call(model='qwen-max', prompt=prompt)
        raw_text = response.output.text.strip()

        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        questions_list = json.loads(raw_text)
        return questions_list, type_name, None

    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
        logger.error(f"AI 原始输出: {raw_text}")
        return None, type_name, 'AI 生成失败: JSON格式错误。请检查控制台日志。'
    except Exception as e:
        logger.error(f"其他错误: {e}")
        return None, type_name, f'AI 生成失败: {str(e)}'


def ai_generate_explanation(question):
    q_type = question['question_type']
    q_text = question['question_text']
    correct_answer = question['correct_answer'] or ''

    if q_type in ('multiple_choice', 'multiple_select', 'true_false'):
        options_text = ''
        for letter in ['a', 'b', 'c', 'd', 'e', 'f']:
            opt = question[f'option_{letter}']
            if opt:
                options_text += f"{letter.upper()}. {opt}\n"
        prompt = f"""
        你是一位经验丰富的教师。请为以下{q_type}题目生成详细的解析。

        题目内容：{q_text}
        选项：
        {options_text}
        正确答案：{correct_answer}

        请直接输出解析内容（纯文本，不要包含 JSON 或代码块标记），解析应包括：
        1. 为什么正确答案是对的
        2. 为什么其他选项是错的
        3. 相关知识点补充
        """
    elif q_type == 'short_answer':
        prompt = f"""
        你是一位经验丰富的教师。请为以下简答题生成详细的解析。

        题目内容：{q_text}
        参考答案：{correct_answer}

        请直接输出解析内容（纯文本），包括答题思路、要点分析和知识点补充。
        """
    elif q_type == 'programming':
        solution = question['solution_code'] or correct_answer or '暂无'
        prompt = f"""
        你是一位经验丰富的编程教师。请为以下编程题生成详细的解析。

        题目内容：{q_text}
        参考答案代码：
        {solution}

        请直接输出解析内容（纯文本），包括解题思路、代码要点和易错点。
        """
    else:
        prompt = f"请为以下题目生成详细解析。\n题目：{q_text}\n正确答案：{correct_answer}\n请直接输出纯文本解析。"

    try:
        response = dashscope.Generation.call(model='qwen-max', prompt=prompt)
        explanation = response.output.text.strip()
        if explanation.startswith('```'):
            explanation = explanation.lstrip('`')
        if explanation.endswith('```'):
            explanation = explanation.rstrip('`')
        return explanation.strip(), None
    except Exception as e:
        logger.error(f"AI 生成解析失败: {e}")
        return None, str(e)