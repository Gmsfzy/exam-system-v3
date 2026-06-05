"""
考试系统v1.2架构：
- 集成多选题、简答题、编程题类型
- 集成代码自动评测功能
- 集成富文本编辑器
- 集成考试防作弊机制
- 包含完整的评分管理系统
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from tenacity import retry, stop_after_attempt, wait_fixed # 用于处理网络重试
import sqlite3
import datetime
import json
import random
import re
import subprocess
import tempfile
import os
import hashlib
import secrets
from PIL import Image
import base64
from io import BytesIO
import threading
import time

# 接入千问大模型
import dashscope
from dashscope import Generation


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

dashscope.api_key = "sk-2682c4e28f7a4be2a0d74c8fb7d0b0d8" # 调用API Key


# 数据库初始化函数
def init_db():
    conn = sqlite3.connect('exam_system.db')
    cursor = conn.cursor()

    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL, -- 'teacher' 或 'student'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建题目表（扩展以支持多种题型）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            option_e TEXT,
            option_f TEXT,
            correct_answer TEXT, -- 对于多选题，用逗号分隔多个答案，如"A,B,C"
            question_type TEXT DEFAULT 'multiple_choice', -- multiple_choice, multiple_select, true_false, short_answer, programming
            subject TEXT,
            difficulty TEXT, -- easy, medium, hard
            points INTEGER DEFAULT 1, -- 题目分值
            test_cases TEXT, -- 编程题的测试用例JSON
            solution_code TEXT, -- 编程题参考答案
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # 创建考试表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT,
            teacher_id INTEGER NOT NULL,
            duration_minutes INTEGER,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            status TEXT DEFAULT 'inactive',     -- 【新增】添加状态字段，默认为禁用/未开始
            anti_cheat_enabled BOOLEAN DEFAULT 0, -- 是否启用防作弊
            shuffle_questions BOOLEAN DEFAULT 0, -- 是否随机打乱题目顺序
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    # 创建考试题目关联表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            FOREIGN KEY (exam_id) REFERENCES exams(id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')

    # 创建考试记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            start_time TIMESTAMP,
            submit_time TIMESTAMP,
            score INTEGER,
            total_questions INTEGER,
            answers TEXT, -- JSON格式存储学生答案
            status TEXT DEFAULT 'in_progress', -- in_progress, submitted
            anti_cheat_logs TEXT, -- 防作弊日志
            FOREIGN KEY (exam_id) REFERENCES exams(id),
            FOREIGN KEY (student_id) REFERENCES users(id)
        )
    ''')

    # 创建评分记录表（用于编程题和简答题的人工评分）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grading_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_record_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            student_answer TEXT,
            teacher_score INTEGER, -- 教师给的分数
            auto_score INTEGER, -- 自动评分分数（主要用于编程题）
            max_score INTEGER, -- 该题最大分值
            grader_id INTEGER, -- 评分教师ID
            graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_record_id) REFERENCES exam_records(id),
            FOREIGN KEY (question_id) REFERENCES questions(id),
            FOREIGN KEY (grader_id) REFERENCES users(id)
        )
    ''')

    # 创建图片附件表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS image_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            exam_record_id INTEGER,
            filename TEXT NOT NULL,
            data BLOB NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id),
            FOREIGN KEY (exam_record_id) REFERENCES exam_records(id)
        )
    ''')

    conn.commit()
    # conn.close()
    # conn = get_db_connection()
    try:
        # 尝试给 exams 表添加 status 列
        # 如果列已存在，这会报错，所以我们用 try-except 忽略它
        conn.execute("ALTER TABLE exams ADD COLUMN status TEXT DEFAULT 'inactive'")
        conn.commit()
        print("✅ 数据库已更新：添加了 status 列")
    except Exception as e:
        # 如果报错说 "duplicate column name"，说明列已经存在，这是好事
        if "duplicate column name" in str(e):
            pass
        else:
            print(f"⚠️ 数据库检查出现其他错误: {e}")
    finally:
        conn.close()


# 在 app 启动时立即执行一次
init_db()


# 辅助函数：获取数据库连接
def get_db_connection():
    conn = sqlite3.connect('exam_system.db')
    conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
    return conn


# 登录装饰器
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# 角色检查装饰器
def role_required(required_role):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))

            conn = get_db_connection()
            user = conn.execute('SELECT role FROM users WHERE id = ?',
                               (session['user_id'],)).fetchone()
            conn.close()

            if user['role'] != required_role:
                flash('您没有权限访问此页面', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# 判断答案是否正确
def is_answer_correct(student_answer, correct_answer, question_type):
    """
    判断学生答案是否正确
    """
    if question_type in ['multiple_choice', 'true_false']:
        return student_answer.upper() == correct_answer.upper()
    elif question_type == 'multiple_select':
        # 多选题：答案是逗号分隔的选项，如"A,B,C"
        student_answers = set(student_answer.upper().split(','))
        correct_answers = set(correct_answer.upper().split(','))
        return student_answers == correct_answers
    elif question_type in ['short_answer', 'programming']:
        # 简答题和编程题需要人工评分或自动评测
        return False
    return False


# 编程题自动评测函数
def evaluate_programming_solution(student_code, test_cases_json, reference_solution=None):
    """
    自动评测编程题解决方案
    :param student_code: 学生提交的代码
    :param test_cases_json: 测试用例JSON字符串
    :param reference_solution: 参考答案（可选）
    :return: 通过的测试用例数，总测试用例数
    """
    try:
        test_cases = json.loads(test_cases_json)
        passed = 0
        total = len(test_cases)

        # 为每个测试用例创建临时文件并执行
        for case in test_cases:
            input_data = case.get('input', '')
            expected_output = case.get('expected_output', '')

            # 创建临时Python文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                # 写入学生代码
                temp_file.write(student_code)
                temp_file.write('\n\n')

                # 添加测试代码
                if input_data.strip():
                    # 如果有输入数据，模拟输入
                    temp_file.write(f'import sys\n')
                    temp_file.write(f'sys.stdin = open("/dev/stdin", "r")\n')
                    temp_file.write(f'original_input = input\n')
                    temp_file.write(f'original_print = print\n')
                    temp_file.write(f'captured_output = []\n')
                    temp_file.write(f'exec(open("{temp_file.name}", "r").read())\n')
                else:
                    # 直接执行学生代码
                    exec_globals = {}
                    exec(student_code, exec_globals)

                    # 获取输出（如果有的话）
                    captured_output = []
                    original_print = print
                    def capture_print(*args, **kwargs):
                        captured_output.extend(args)
                    print = capture_print

                    # 执行代码
                    exec(student_code, {'print': capture_print})

                    output = ''.join(str(x) for x in captured_output).strip()

                    # 比较输出
                    if output == expected_output.strip():
                        passed += 1

        return passed, total
    except Exception as e:
        # 发生错误时，认为所有测试用例都失败
        return 0, len(json.loads(test_cases_json)) if test_cases_json else 0


def grade_short_answer_ai(question_text, standard_answer_hint, student_answer):
    """
    利用大模型对简答题进行语义评分
    :param question_text: 题目内容
    :param standard_answer_hint: 参考答案/得分点（存放在 correct_answer 字段里的）
    :param student_answer: 学生作答
    :return: 得分 (int), 评语 (str)
    """
    # 构建 Prompt (这是核心，Prompt 写得好，评分才准)
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
        response = dashscope.Generation.call(
            model='qwen-max',  # 模型名称，也可以用 qwen-plus
            prompt=prompt
        )

        # 解析返回的 JSON
        result_text = response.output.text.strip()
        # 这里需要处理一下，有时候模型会带 ```json 包裹
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 2)[2].rstrip("`")

        result = json.loads(result_text)
        ai_score = int(result['score'])
        ai_comment = result['comment']

        return ai_score, ai_comment

    except Exception as e:
        print(f"AI 评分出错: {e}")
        # 出错时返回一个中间值，或者标记为待人工复核
        return 5, "AI 评分系统暂时繁忙，此为暂定分数。"
        return None, "AI 评分系统暂时繁忙，请人工复核"


# 防作弊检测函数
def detect_cheating(session_id, action, details=None):
    """
    记录可能的作弊行为
    :param session_id: 考试记录ID
    :param action: 作弊行为类型
    :param details: 行为详情
    """
    # timestamp = datetime.datetime.now()
    # log_entry = {
    #     'timestamp': timestamp.isoformat(),
    #     'action': action,
    #     'details': details
    # }
    #
    # # 将日志追加到考试记录的anti_cheat_logs字段
    # conn = get_db_connection()
    # record = conn.execute('SELECT anti_cheat_logs FROM exam_records WHERE id = ?', (session_id,)).fetchone()
    #
    # logs = json.loads(record['anti_cheat_logs']) if record['anti_cheat_logs'] else []
    # logs.append(log_entry)
    #
    # conn.execute('UPDATE exam_records SET anti_cheat_logs = ? WHERE id = ?',
    #              (json.dumps(logs), session_id))
    # conn.commit()
    # conn.close()

    conn = get_db_connection()
    try:
        record = conn.execute('SELECT anti_cheat_logs FROM exam_records WHERE id = ?', (session_id,)).fetchone()

        # ✅ 核心修复1：防御记录不存在的情况
        if record is None:
            print(f"[WARNING] 反作弊日志写入失败: 找不到 exam_record id={session_id}")
            return

        # ✅ 核心修复2：防御字段为 None 或非法 JSON 字符串的情况
        raw_logs = record['anti_cheat_logs']
        try:
            logs = json.loads(raw_logs) if raw_logs else []
        except (json.JSONDecodeError, TypeError):
            print(f"[WARNING] exam_record id={session_id} 的 anti_cheat_logs JSON 解析失败，已重置")
            logs = []

        timestamp = datetime.datetime.now()
        log_entry = {
            'timestamp': timestamp.isoformat(),
            'action': action,
            'details': details
        }
        logs.append(log_entry)

        conn.execute('UPDATE exam_records SET anti_cheat_logs = ? WHERE id = ?',
                     (json.dumps(logs), session_id))
        conn.commit()
    finally:
        # ✅ 核心修复3：确保数据库连接在任何情况下都能被正确关闭
        conn.close()


# 路由：主页
@app.route('/')
def index():
    return render_template('index.html')


# 路由：注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db_connection()
            conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                        (username, hashed_password, role))
            conn.commit()
            conn.close()

            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在', 'error')

    return render_template('register.html')


# 路由：登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?',
                           (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


# 路由：登出
@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('index'))


# 路由：仪表板
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()

    if session['role'] == 'teacher':
        # 教师视图：显示他们创建的考试和题目
        exams = conn.execute(
            'SELECT e.*, COUNT(eq.id) as question_count FROM exams e '
            'LEFT JOIN exam_questions eq ON e.id = eq.exam_id '
            'WHERE e.teacher_id = ? GROUP BY e.id ORDER BY e.created_at DESC',
            (session['user_id'],)
        ).fetchall()

        questions = conn.execute(
            'SELECT * FROM questions WHERE teacher_id = ? ORDER BY created_at DESC',
            (session['user_id'],)
        ).fetchall()

        # 获取待评分的考试记录
        pending_grading = conn.execute('''
            SELECT er.*, e.title, u.username as student_name FROM exam_records er
            JOIN exams e ON er.exam_id = e.id
            JOIN users u ON er.student_id = u.id
            WHERE er.status = 'submitted' AND er.score IS NULL
        ''').fetchall()

        conn.close()
        return render_template('teacher_dashboard.html', exams=exams, questions=questions, pending_grading=pending_grading)

    elif session['role'] == 'student':
        # 学生视图：显示可用的考试
        # ✅ 统一使用 Python 本地时间，避免 SQLite datetime('now') 的 UTC 时区陷阱
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user_id = session['user_id']

        print(f"[DEBUG] current_time = '{current_time}'")
        print(f"[DEBUG] type(current_time) = {type(current_time)}")


        # === 1. 获取【正在进行】的考试（新增） ===
        current_exams = conn.execute(
            '''SELECT e.id, e.title, e.subject, e.start_time, e.end_time, e.status, u.username as teacher_name
               FROM exams e
                        INNER JOIN users u ON e.teacher_id = u.id
               WHERE e.status = 'active'
                 AND (e.start_time IS NULL OR e.start_time <= :ct)
                 AND (e.end_time IS NULL OR e.end_time >= :ct)
                 AND e.id NOT IN (SELECT exam_id
                                  FROM exam_records
                                  WHERE student_id = :uid
                                    AND status = 'completed')''',
            {"ct": current_time, "uid": user_id}
        ).fetchall()

        # === 2. 获取【即将开始】的考试（保持原逻辑） ===
        upcoming_exams = conn.execute(
            '''SELECT e.id, e.title, e.subject, e.start_time, e.end_time, e.status, u.username as teacher_name
               FROM exams e
                        INNER JOIN users u ON e.teacher_id = u.id
               WHERE e.status = 'active'
                 AND e.start_time > :ct
                 AND e.id NOT IN (SELECT exam_id
                                  FROM exam_records
                                  WHERE student_id = :uid)''',
            {"ct": current_time, "uid": user_id}
        ).fetchall()

        # === 3. 获取【历史考试记录】 ===
        completed_exams = conn.execute(
            '''SELECT er.*, e.title AS exam_name, u.username as teacher_name
               FROM exam_records er
                        JOIN exams e ON er.exam_id = e.id
                        JOIN users u ON e.teacher_id = u.id
               WHERE er.student_id = :uid
               ORDER BY er.id DESC''',
            {"uid": user_id}
        ).fetchall()

        conn.close()  # ✅ 提前关闭连接，防止资源泄漏

        # === 4. 渲染模板时传入新变量 ===
        return render_template(
            'student_dashboard.html',
            current_exams=current_exams,
            upcoming_exams=upcoming_exams,
            completed_exams=completed_exams
        )


# 路由：教师 - 添加题目
@app.route('/add_question', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def add_question():
    if request.method == 'POST':
        question_text = request.form['question_text']
        question_type = request.form['question_type']
        subject = request.form['subject']
        difficulty = request.form['difficulty']
        points = int(request.form.get('points', 1))

        # 根据题型处理不同字段
        if question_type in ['multiple_choice', 'multiple_select', 'true_false']:
            option_a = request.form.get('option_a')
            option_b = request.form.get('option_b')
            option_c = request.form.get('option_c')
            option_d = request.form.get('option_d')
            option_e = request.form.get('option_e')
            option_f = request.form.get('option_f')
            correct_answer = request.form['correct_answer']
            test_cases = None
            solution_code = None
        elif question_type == 'programming':
            option_a = option_b = option_c = option_d = option_e = option_f = None
            correct_answer = ""
            test_cases = request.form.get('test_cases', '[]')
            solution_code = request.form.get('solution_code', '')
        else:  # 简答题
            option_a = option_b = option_c = option_d = option_e = option_f = None
            correct_answer = ""
            test_cases = None
            solution_code = None

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO questions (teacher_id, question_text, option_a, option_b, option_c, option_d, option_e, option_f, 
                                 correct_answer, question_type, subject, difficulty, points, test_cases, solution_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], question_text, option_a, option_b, option_c, option_d, option_e, option_f,
              correct_answer, question_type, subject, difficulty, points, test_cases, solution_code))

        conn.commit()
        conn.close()

        flash('题目添加成功', 'success')
        return redirect(url_for('dashboard'))

    return render_template('add_question.html')


# 路由：教师 - 创建考试
@app.route('/create_exam', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def create_exam():
    if request.method == 'POST':
        exam_name = request.form['exam_name']
        subject = request.form['subject']
        duration_minutes = int(request.form['duration_minutes'])
        anti_cheat_enabled = 'anti_cheat_enabled' in request.form
        shuffle_questions = 'shuffle_questions' in request.form

        # 解析开始和结束时间
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')

        # start_time = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) if start_time_str else None
        # end_time = datetime.datetime.fromisoformat(end_time_str.replace('Z', '+00:00')) if end_time_str else None

        # ✅ 修复：解析后立即转为标准字符串格式，避免 sqlite3 自动序列化带来的格式灾难
        start_time = None
        if start_time_str:
            dt_obj = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            start_time = dt_obj.strftime('%Y-%m-%d %H:%M:%S')

        end_time = None
        if end_time_str:
            dt_obj = datetime.datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
            end_time = dt_obj.strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()

        # 创建考试
        conn.execute('''
            INSERT INTO exams (title, subject, teacher_id, duration_minutes, start_time, end_time, anti_cheat_enabled, shuffle_questions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (exam_name, subject, session['user_id'], duration_minutes, start_time, end_time, anti_cheat_enabled, shuffle_questions))

        exam_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # 添加选定的题目到考试中
        selected_questions = request.form.getlist('questions')
        for qid in selected_questions:
            conn.execute('INSERT INTO exam_questions (exam_id, question_id) VALUES (?, ?)', (exam_id, qid))

        conn.commit()
        conn.close()

        flash('考试创建成功', 'success')
        return redirect(url_for('dashboard'))

    # 获取教师的所有题目
    conn = get_db_connection()
    questions = conn.execute('SELECT * FROM questions WHERE teacher_id = ?', (session['user_id'],)).fetchall()
    conn.close()

    return render_template('create_exam.html', questions=questions)


# 路由：学生 - 参加考试
@app.route('/take_exam/<int:exam_id>')
@login_required
@role_required('student')
def take_exam(exam_id):
    conn = get_db_connection()

    # 获取考试信息
    exam = conn.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()
    if not exam:
        flash('考试不存在', 'error')
        return redirect(url_for('dashboard'))

    # ✅ 修复：使用统一格式的字符串进行时间比较，彻底告别 fromisoformat 解析异常
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if exam['start_time'] and now_str < exam['start_time']:
        flash('考试尚未开始', 'error')
        return redirect(url_for('dashboard'))

    if exam['end_time'] and now_str > exam['end_time']:
        flash('考试已结束', 'error')
        return redirect(url_for('dashboard'))

    # 获取考试题目
    questions_query = '''
        SELECT q.* FROM questions q 
        JOIN exam_questions eq ON q.id = eq.question_id 
        WHERE eq.exam_id = ?
    '''
    params = [exam_id]

    # 如果启用了随机打乱题目顺序
    if exam['shuffle_questions']:
        questions_query += ' ORDER BY RANDOM()'
    else:
        questions_query += ' ORDER BY q.id'

    questions = conn.execute(questions_query, params).fetchall()

    # 检查是否已有考试记录
    existing_record = conn.execute('''
        SELECT * FROM exam_records 
        WHERE exam_id = ? AND student_id = ? AND status = 'in_progress'
    ''', (exam_id, session['user_id'])).fetchone()

    if existing_record:
        record_id = existing_record['id']
    else:
        # 创建新的考试记录
        start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute('''
                              INSERT INTO exam_records (exam_id, student_id, start_time, status, anti_cheat_logs)
                              VALUES (?, ?, ?, 'in_progress', ?)
                              ''', (exam_id, session['user_id'], start_time, json.dumps([])))

        # record_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        record_id = cursor.lastrowid

        conn.commit()

    conn.close()

    return render_template('take_exam.html',
                          exam=exam,
                          questions=questions,
                          record_id=record_id,
                          anti_cheat_enabled=exam['anti_cheat_enabled'])


# 路由：提交考试答案
@app.route('/submit_exam/<int:record_id>', methods=['POST'])
@login_required
@role_required('student')
def submit_exam(record_id):
    # 获取所有提交的答案
    answers = {}
    images = {}  # 存储图片数据

    for key, value in request.form.items():
        if key.startswith('question_'):
            question_id = key.split('_')[1]
            answers[question_id] = value
        elif key.startswith('image_'):
            question_id = key.split('_')[1]
            images[question_id] = value  # Base64编码的图片数据

    conn = get_db_connection()

    # 获取考试记录
    record = conn.execute('SELECT * FROM exam_records WHERE id = ?', (record_id,)).fetchone()
    if not record or record['status'] != 'in_progress':
        flash('无效的考试记录', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    # 获取考试和题目信息
    exam = conn.execute('SELECT * FROM exams WHERE id = ?', (record['exam_id'],)).fetchone()
    questions = conn.execute('''
        SELECT q.* FROM questions q 
        JOIN exam_questions eq ON q.id = eq.question_id 
        WHERE eq.exam_id = ?
    ''', (record['exam_id'],)).fetchall()

    # 计算客观题分数
    score = 0
    total_questions = len(questions)
    subjective_questions = []  # 需要人工评分的题目
    programming_questions = []  # 需要自动评测的编程题

    for question in questions:
        question_id = str(question['id'])
        if question_id in answers:
            answer = answers[question_id]

            # 根据题型判断答案是否正确
            if question['question_type'] in ['multiple_choice', 'true_false']:
                if is_answer_correct(answer, question['correct_answer'], question['question_type']):
                    score += question['points']
            elif question['question_type'] == 'multiple_select':
                student_answers = set(answer.upper().split(',')) if answer else set()
                correct_answers = set(question['correct_answer'].upper().split(','))
                if student_answers == correct_answers:
                    score += question['points']
            elif question['question_type'] == 'programming':
                # 编程题：先进行自动评测，再人工评分
                if question['test_cases']:  # 如果有测试用例
                    passed, total_tests = evaluate_programming_solution(
                        answer, question['test_cases'], question['solution_code']
                    )
                    auto_score = int((passed / total_tests) * question['points']) if total_tests > 0 else 0

                    programming_questions.append({
                        'question_id': question['id'],
                        'answer': answer,
                        'auto_score': auto_score,
                        'max_score': question['points']
                    })
                else:
                    # 没有测试用例的编程题需要人工评分
                    subjective_questions.append({
                        'question_id': question['id'],
                        'answer': answer,
                        'points': question['points']
                    })
            elif question['question_type'] == 'short_answer':
                student_answer = answers.get(question_id, "")

                # 如果学生没写，给0分
                if not student_answer.strip():
                    # 依然存入记录，标记为 AI 评0分
                    conn.execute(''' INSERT INTO grading_records ... ''')
                    continue

                # --- 调用 AI 进行实时评分 ---
                # 注意：standard_answer 字段里存的是“得分点关键词”
                standard_hint = question['correct_answer']

                ai_raw_score, ai_comment = grade_short_answer_ai(
                    question['question_text'],
                    standard_hint,
                    student_answer
                )

                # 将 0-10 的分数映射到该题的实际分值
                # 例如该题 5 分，AI 打了 8 分（满分10），则实际得分 = 8/10 * 5 = 4
                max_points = question['points']
                actual_score = int((ai_raw_score / 10) * max_points)

                # 累加到总分
                score += actual_score

                # 存入数据库，标记为 AI 评分
                conn.execute(
                    '''
                        INSERT INTO grading_records 
                        (exam_record_id, question_id, student_answer, teacher_score, max_score, grader_id) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''',(record_id, question['id'], student_answer, actual_score, max_points, -1))
                # -1 代表 AI


                # 人工评分简答题
                # subjective_questions.append({
                #     'question_id': question['id'],
                #     'answer': answer,
                #     'points': question['points']
                # })

    # 更新考试记录
    submit_time = datetime.datetime.now()

    # 如果有主观题或编程题需要人工评分，分数暂时设为None
    has_manual_grading = bool(subjective_questions or any(q['auto_score'] < q['max_score'] for q in programming_questions))
    final_score = score if not has_manual_grading else None

    conn.execute('''
        UPDATE exam_records 
        SET submit_time = ?, score = ?, total_questions = ?, answers = ?, status = 'submitted'
        WHERE id = ?
    ''', (submit_time, final_score, total_questions, json.dumps(answers), record_id))

    # 保存主观题和编程题答案以供后续评分
    for subj_q in subjective_questions:
        conn.execute('''
            INSERT INTO grading_records (exam_record_id, question_id, student_answer, max_score)
            VALUES (?, ?, ?, ?)
        ''', (record_id, subj_q['question_id'], subj_q['answer'], subj_q['points']))

    for prog_q in programming_questions:
        conn.execute('''
            INSERT INTO grading_records (exam_record_id, question_id, student_answer, auto_score, max_score)
            VALUES (?, ?, ?, ?, ?)
        ''', (record_id, prog_q['question_id'], prog_q['answer'], prog_q['auto_score'], prog_q['max_score']))

    # 保存图片附件
    for qid, img_data in images.items():
        if img_data:
            # 解码Base64图片数据
            header, encoded = img_data.split(',', 1)
            image_data = base64.b64decode(encoded)

            # 生成唯一文件名
            filename = f"{secrets.token_hex(8)}.png"

            conn.execute('''
                INSERT INTO image_attachments (question_id, exam_record_id, filename, data)
                VALUES (?, ?, ?, ?)
            ''', (qid, record_id, filename, image_data))

    conn.commit()
    conn.close()

    # 准备反馈消息
    feedback_parts = []
    if score > 0:
        feedback_parts.append(f'客观题得分: {score}')

    if programming_questions:
        auto_score_total = sum(q['auto_score'] for q in programming_questions)
        if auto_score_total > 0:
            feedback_parts.append(f'编程题自动评分得分: {auto_score_total}')

    if subjective_questions or any(q['auto_score'] < q['max_score'] for q in programming_questions):
        feedback_parts.append('主观题和部分编程题待教师评分')

    if feedback_parts:
        flash(f'考试提交成功！{". ".join(feedback_parts)}。', 'success')
    else:
        flash(f'考试提交成功！您的得分是 {score} 分', 'success')

    # return redirect(url_for('dashboard'))
    # 【修改点】不再返回 dashboard，而是跳转到专属的结果解析页
    return redirect(url_for('view_exam_result', record_id=record_id))


# 评分反馈以及严格权限校验
@app.route('/exam_result/<int:record_id>')
@login_required
@role_required('student')
def view_exam_result(record_id):
    conn = get_db_connection()

    # 【安全校验】强制绑定当前登录用户 ID，防止越权访问
    record = conn.execute(
        'SELECT * FROM exam_records WHERE id = ? AND student_id = ?',
        (record_id, session['user_id'])
    ).fetchone()

    if not record:
        flash('未找到考试记录或无权访问', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    student_answers = json.loads(record['answers']) if record['answers'] else {}

    # 获取题目详情及解析
    questions = conn.execute('''
                             SELECT q.id,
                                    q.question_text,
                                    q.question_type,
                                    q.options,
                                    q.correct_answer,
                                    q.explanation,
                                    q.points
                             FROM exam_questions eq
                                      JOIN questions q ON eq.question_id = q.id
                             WHERE eq.exam_id = ?
                             ORDER BY eq.id
                             ''', (record['exam_id'],)).fetchall()

    # 【关键增强】获取主观题/编程题的评分记录（含AI评语/得分）
    grading_map = {}
    subjective_ids = [q['id'] for q in questions if q['question_type'] in ('short_answer', 'programming')]
    if subjective_ids:
        placeholders = ','.join(['?'] * len(subjective_ids))
        gradings = conn.execute(f'''
            SELECT question_id, teacher_score, max_score, grader_id 
            FROM grading_records 
            WHERE exam_record_id = ? AND question_id IN ({placeholders})
        ''', [record_id] + subjective_ids).fetchall()

        for g in gradings:
            grading_map[g['question_id']] = dict(g)

    conn.close()

    return render_template(
        'exam_result.html',
        record=record,
        questions=questions,
        student_answers=student_answers,
        grading_map=grading_map
    )


# 路由：处理防作弊事件
@app.route('/cheating_detected/<int:record_id>', methods=['POST'])
@login_required
@role_required('student')
def cheating_detected(record_id):
    data = request.json
    action = data.get('action')
    details = data.get('details')

    # 记录作弊行为
    detect_cheating(record_id, action, details)

    return jsonify({'status': 'logged'})


# 路由：教师 - 查看考试结果
@app.route('/exam_results/<int:exam_id>')
@login_required
@role_required('teacher')
def exam_results(exam_id):
    conn = get_db_connection()

    # 获取考试信息
    exam = conn.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()

    # 获取考试结果
    results = conn.execute('''
        SELECT er.*, u.username as student_name FROM exam_records er
        JOIN users u ON er.student_id = u.id
        WHERE er.exam_id = ? AND er.status = 'submitted'
        ORDER BY er.score DESC NULLS LAST
    ''', (exam_id,)).fetchall()

    conn.close()

    if results:
        max_score = max(r.score for r in results) if results else 0
        min_score = min(r.score for r in results) if results else 0
    else:
        max_score = 0
        min_score = 0

    return render_template('exam_results.html',
                           exam=exam,
                           results=results,
                           max_score=max_score,
                           min_score=min_score)


# 路由：教师 - 评分主观题
@app.route('/grade_subjective_questions', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def grade_subjective_questions():
    if request.method == 'POST':
        # 处理评分提交
        conn = get_db_connection()

        for key, value in request.form.items():
            if key.startswith('score_'):
                grading_record_id = key.split('_')[1]
                score = int(value)

                # 更新评分记录
                conn.execute('''
                    UPDATE grading_records 
                    SET teacher_score = ?, grader_id = ?
                    WHERE id = ?
                ''', (score, session['user_id'], grading_record_id))

        # 计算每个考试记录的最终分数
        # 获取所有已完成评分的考试记录
        completed_gradings = conn.execute('''
            SELECT gr.exam_record_id, SUM(COALESCE(gr.teacher_score, gr.auto_score, 0)) as subjective_score
            FROM grading_records gr
            WHERE gr.teacher_score IS NOT NULL OR gr.auto_score IS NOT NULL
            GROUP BY gr.exam_record_id
        ''').fetchall()

        for record in completed_gradings:
            exam_record_id = record['exam_record_id']

            # 计算客观题分数
            objective_data = conn.execute(
        '''
                SELECT SUM(q.points) as objective_score
                FROM exam_records er
                JOIN exams e ON er.exam_id = e.id
                JOIN exam_questions eq ON e.id = eq.exam_id
                JOIN questions q ON eq.question_id = q.id
                WHERE er.id = ? AND q.question_type IN ('multiple_choice', 'multiple_select', 'true_false')
            ''', (exam_record_id,)).fetchone()

            objective_score = objective_data['objective_score'] or 0

            # 总分 = 客观题分数 + 主观题分数
            total_score = objective_score + (record['subjective_score'] or 0)

            # 更新考试记录的总分
            conn.execute('''
                UPDATE exam_records 
                SET score = ?
                WHERE id = ?
            ''', (total_score, exam_record_id))

        conn.commit()
        conn.close()

        flash('评分提交成功！', 'success')
        return redirect(url_for('dashboard'))

    # 显示待评分的题目
    conn = get_db_connection()

    # 获取需要评分的记录
    records_to_grade = conn.execute('''
        SELECT gr.*, q.question_text, u.username as student_name, e.title
        FROM grading_records gr
        JOIN questions q ON gr.question_id = q.id
        JOIN exam_records er ON gr.exam_record_id = er.id
        JOIN exams e ON er.exam_id = e.id
        JOIN users u ON er.student_id = u.id
        WHERE gr.teacher_score IS NULL
        ORDER BY e.id, u.username
    ''').fetchall()

    conn.close()

    return render_template('grade_subjective_questions.html', records_to_grade=records_to_grade)


# 路由：获取图片附件
@app.route('/image_attachment/<int:attachment_id>')
@login_required
def get_image_attachment(attachment_id):
    conn = get_db_connection()
    attachment = conn.execute('SELECT * FROM image_attachments WHERE id = ?', (attachment_id,)).fetchone()
    conn.close()

    if not attachment:
        return '', 404

    response = app.response_class(
        response=attachment['data'],
        status=200,
        mimetype='image/png'
    )
    return response


# 路由：AI 一键出题 (解决随机生成试题)，AI 自动生成题目存入数据库
@app.route('/ai_generate', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def ai_generate():
    if request.method == 'POST':
        topic = request.form['topic']
        difficulty = request.form['difficulty']
        num = int(request.form['num'])

        # 优化 Prompt：明确要求字段名
        prompt = f"""
        你是一个出题助手。请生成 {num} 道关于 '{topic}' 的 {difficulty} 难度的单选题。
        请严格遵守以下 JSON 格式，不要包含 Markdown 代码块标记（```），不要包含任何解释性文字：
        [
            {{
                "question_text": "题目内容（如果有数学公式，请用普通文本描述，不要使用 LaTeX 括号）",
                "option_a": "选项A内容",
                "option_b": "选项B内容",
                "option_c": "选项C内容",
                "option_d": "选项D内容",
                "correct_answer": "A"
            }}
        ]
        """

        try:
            response = dashscope.Generation.call(model='qwen-max', prompt=prompt)
            raw_text = response.output.text.strip()

            # 1. 清洗数据：去除可能存在的 Markdown 标记
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            # 2. 直接解析 JSON (不再使用正则修复，避免误伤数学符号)
            questions_list = json.loads(raw_text)

            # 3. 存入数据库
            conn = get_db_connection()
            success_count = 0

            for q in questions_list:
                # 兼容处理：检查 key 是否存在
                # 如果 AI 还是返回了 'options' 列表，我们需要拆分它（可选，视情况而定）
                # 这里我们强制要求 AI 返回拆分好的字段，所以直接取值

                conn.execute('''
                    INSERT INTO questions
                    (teacher_id, question_text, option_a, option_b, option_c, option_d, correct_answer, question_type, subject, difficulty, points)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'multiple_choice', ?, ?, 1)
                ''', (
                    session['user_id'],
                    q.get('question_text', q.get('question', '')), # 兼容两种 key
                    q.get('option_a', ''),
                    q.get('option_b', ''),
                    q.get('option_c', ''),
                    q.get('option_d', ''),
                    q.get('correct_answer', q.get('answer', '')), # 兼容两种 key
                    topic,
                    difficulty
                ))
                success_count += 1

            conn.commit()
            conn.close()
            flash(f'成功生成并导入 {success_count} 道题目！')

        except json.JSONDecodeError as e:
            # 专门捕获 JSON 错误，打印出来方便调试
            print(f"JSON 解析错误: {e}")
            print(f"AI 原始输出: {raw_text}")
            flash(f'AI 生成失败: JSON格式错误。请检查控制台日志。')

        except Exception as e:
            print(f"其他错误: {e}")
            flash(f'AI 生成失败: {str(e)}')

    return render_template('ai_generate.html')


# 教师题库管理
@app.route('/manage_questions')
@login_required
@role_required('teacher')
def manage_questions():
    """教师管理题库页面"""
    conn = get_db_connection()
    # 查询当前教师的所有题目
    questions = conn.execute(
        'SELECT * FROM questions WHERE teacher_id = ? ORDER BY id DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template('manage_questions.html', questions=questions)


@app.route('/edit_question/<int:question_id>', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def edit_question(question_id):
    """编辑题目"""
    conn = get_db_connection()

    if request.method == 'POST':
        question_text = request.form['question_text']
        option_a = request.form['option_a']
        option_b = request.form['option_b']
        option_c = request.form['option_c']
        option_d = request.form['option_d']
        correct_answer = request.form['correct_answer']
        subject = request.form['subject']
        difficulty = request.form['difficulty']

        conn.execute('''
                     UPDATE questions
                     SET question_text=?,
                         option_a=?,
                         option_b=?,
                         option_c=?,
                         option_d=?,
                         correct_answer=?,
                         subject=?,
                         difficulty=?
                     WHERE id = ?
                     ''', (question_text, option_a, option_b, option_c, option_d, correct_answer, subject, difficulty,
                           question_id))
        conn.commit()
        conn.close()
        flash('✅ 题目已更新！', 'success')
        return redirect(url_for('manage_questions'))

    question = conn.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
    conn.close()
    if not question:
        flash('❌ 题目不存在！', 'error')
        return redirect(url_for('manage_questions'))
    return render_template('edit_question.html', question=question)


@app.route('/delete_question/<int:question_id>', methods=['POST'])
@login_required
@role_required('teacher')
def delete_question(question_id):
    """删除题目"""
    conn = get_db_connection()
    conn.execute('DELETE FROM questions WHERE id = ?', (question_id,))
    conn.commit()
    conn.close()
    flash('❌ 题目已删除！', 'success')
    return redirect(url_for('manage_questions'))


# 路由：禁用/启用考试
@app.route('/toggle_exam_status/<int:exam_id>', methods=['POST'])
@login_required
@role_required('teacher')
def toggle_exam_status(exam_id):
    """切换考试状态（激活/禁用）"""
    try:
        conn = get_db_connection()
        exam = conn.execute('SELECT status FROM exams WHERE id = ?', (exam_id,)).fetchone()

        if exam:
            new_status = 'inactive' if exam['status'] == 'active' else 'active'
            conn.execute('UPDATE exams SET status = ? WHERE id = ?', (new_status, exam_id))
            conn.commit()

            status_text = '禁用' if new_status == 'inactive' else '启用'
            flash(f'✅ 考试已{status_text}！', 'success')

        conn.close()
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f'❌ 操作失败: {str(e)}', 'error')
        return redirect(url_for('dashboard'))


# 路由：清空考试成绩
@app.route('/clear_exam_scores/<int:exam_id>', methods=['POST'])
@login_required
@role_required('teacher')
def clear_exam_scores(exam_id):
    """清空某场考试的所有成绩"""
    try:
        conn = get_db_connection()
        # 删除该考试的所有成绩记录
        cursor = conn.execute('DELETE FROM exam_results WHERE exam_id = ?', (exam_id,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        flash(f'✅ 已清空 {deleted_count} 条考试成绩！', 'success')
        return redirect(url_for('exam_results', exam_id=exam_id))
    except Exception as e:
        flash(f'❌ 清空成绩失败: {str(e)}', 'error')
        return redirect(url_for('exam_results', exam_id=exam_id))


# 路由：删除考试
@app.route('/delete_exam/<int:exam_id>', methods=['POST'])
@login_required
@role_required('teacher')
def delete_exam(exam_id):
    """删除考试及其相关数据"""
    try:
        conn = get_db_connection()

        # 删除该考试的所有成绩记录
        conn.execute('DELETE FROM exam_records WHERE exam_id = ?', (exam_id,))

        # 删除该考试的所有题目关联
        conn.execute('DELETE FROM exam_questions WHERE exam_id = ?', (exam_id,))

        # 删除考试本身
        conn.execute('DELETE FROM exams WHERE id = ?', (exam_id,))

        conn.commit()
        conn.close()

        flash('✅ 考试已成功删除！', 'success')
        return redirect(url_for('dashboard'))

    except Exception as e:
        flash(f'❌ 删除考试失败: {str(e)}', 'error')
        return redirect(url_for('dashboard'))


if __name__ == '__main__':
    # init_db()  # 初始化数据库
    app.run(debug=True)