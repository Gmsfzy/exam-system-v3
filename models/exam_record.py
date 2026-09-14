import json
import datetime
import logging

from models.db import get_db

logger = logging.getLogger(__name__)


def create_exam_record(conn, exam_id, student_id, start_time):
    cursor = conn.execute(
        'INSERT INTO exam_records (exam_id, student_id, start_time, status, anti_cheat_logs) VALUES (?, ?, ?, \'in_progress\', ?)',
        (exam_id, student_id, start_time, json.dumps([]))
    )
    return cursor.lastrowid


def get_exam_record_by_id(record_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM exam_records WHERE id = ?', (record_id,)).fetchone()


def get_in_progress_record(exam_id, student_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM exam_records WHERE exam_id = ? AND student_id = ? AND status = \'in_progress\'',
            (exam_id, student_id)
        ).fetchone()


def update_exam_record_submit(conn, record_id, submit_time, score, total_questions, answers):
    conn.execute('''
        UPDATE exam_records SET submit_time = ?, score = ?, total_questions = ?, answers = ?, status = 'submitted'
        WHERE id = ?
    ''', (submit_time, score, total_questions, answers, record_id))


def get_anti_cheat_logs(record_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT anti_cheat_logs FROM exam_records WHERE id = ?', (record_id,)
        ).fetchone()


def update_anti_cheat_logs(conn, record_id, logs_json):
    conn.execute('UPDATE exam_records SET anti_cheat_logs = ? WHERE id = ?',
                 (logs_json, record_id))
    conn.commit()


def detect_cheating(record_id, action, details=None):
    with get_db() as conn:
        record = get_anti_cheat_logs(record_id)
        if record is None:
            logger.warning(f"反作弊日志写入失败: 找不到 exam_record id={record_id}")
            return

        raw_logs = record['anti_cheat_logs']
        try:
            logs = json.loads(raw_logs) if raw_logs else []
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"exam_record id={record_id} 的 anti_cheat_logs JSON 解析失败，已重置")
            logs = []

        timestamp = datetime.datetime.now()
        log_entry = {
            'timestamp': timestamp.isoformat(),
            'action': action,
            'details': details
        }
        logs.append(log_entry)
        update_anti_cheat_logs(conn, record_id, json.dumps(logs))


def get_pending_grading_records():
    with get_db() as conn:
        return conn.execute('''
            SELECT er.*, e.title, u.username as student_name FROM exam_records er
            JOIN exams e ON er.exam_id = e.id
            JOIN users u ON er.student_id = u.id
            WHERE er.status = 'submitted' AND er.score IS NULL
        ''').fetchall()


def get_exam_results_list(exam_id):
    with get_db() as conn:
        return conn.execute('''
            SELECT er.*, u.username as student_name FROM exam_records er
            JOIN users u ON er.student_id = u.id
            WHERE er.exam_id = ? AND er.status = 'submitted'
            ORDER BY er.score DESC NULLS LAST
        ''', (exam_id,)).fetchall()


def clear_exam_scores_cascade(conn, exam_id):
    conn.execute('''
        DELETE FROM grading_records
        WHERE exam_record_id IN (SELECT id FROM exam_records WHERE exam_id = ?)
    ''', (exam_id,))
    cursor = conn.execute('DELETE FROM exam_records WHERE exam_id = ?', (exam_id,))
    deleted_count = cursor.rowcount
    conn.commit()
    return deleted_count


def get_student_record_with_answer(record_id, student_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM exam_records WHERE id = ? AND student_id = ?',
            (record_id, student_id)
        ).fetchone()


def get_exam_questions_for_result(exam_id):
    with get_db() as conn:
        return conn.execute('''
            SELECT q.id, q.question_text, q.question_type, q.option_a, q.option_b,
                   q.option_c, q.option_d, q.option_e, q.option_f, q.correct_answer,
                   q.points, q.solution_code, q.explanation
            FROM exam_questions eq
            JOIN questions q ON eq.question_id = q.id
            WHERE eq.exam_id = ?
            ORDER BY eq.id
        ''', (exam_id,)).fetchall()


def get_grading_map(record_id, question_ids):
    if not question_ids:
        return {}
    with get_db() as conn:
        placeholders = ','.join(['?'] * len(question_ids))
        gradings = conn.execute(f'''
            SELECT question_id, teacher_score, max_score, grader_id
            FROM grading_records
            WHERE exam_record_id = ? AND question_id IN ({placeholders})
        ''', [record_id] + question_ids).fetchall()
        return {g['question_id']: dict(g) for g in gradings}