from models.db import get_db


def create_grading_record(conn, exam_record_id, question_id, student_answer,
                          teacher_score=None, auto_score=None, max_score=None, grader_id=None):
    if teacher_score is not None and grader_id is not None:
        conn.execute('''
            INSERT INTO grading_records (exam_record_id, question_id, student_answer, teacher_score, max_score, grader_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (exam_record_id, question_id, student_answer, teacher_score, max_score, grader_id))
    elif auto_score is not None:
        conn.execute('''
            INSERT INTO grading_records (exam_record_id, question_id, student_answer, auto_score, max_score)
            VALUES (?, ?, ?, ?, ?)
        ''', (exam_record_id, question_id, student_answer, auto_score, max_score))
    else:
        conn.execute('''
            INSERT INTO grading_records (exam_record_id, question_id, student_answer, max_score)
            VALUES (?, ?, ?, ?)
        ''', (exam_record_id, question_id, student_answer, max_score))


def update_grading_score(conn, grading_record_id, score, grader_id):
    conn.execute('''
        UPDATE grading_records SET teacher_score = ?, grader_id = ? WHERE id = ?
    ''', (score, grader_id, grading_record_id))


def get_completed_gradings():
    with get_db() as conn:
        return conn.execute('''
            SELECT gr.exam_record_id, SUM(COALESCE(gr.teacher_score, gr.auto_score, 0)) as subjective_score
            FROM grading_records gr
            WHERE gr.teacher_score IS NOT NULL OR gr.auto_score IS NOT NULL
            GROUP BY gr.exam_record_id
        ''').fetchall()


def get_objective_questions_for_record(exam_record_id):
    with get_db() as conn:
        return conn.execute('''
            SELECT q.id, q.correct_answer, q.question_type, q.points
            FROM exam_questions eq
            JOIN questions q ON eq.question_id = q.id
            JOIN exams e ON eq.exam_id = e.id
            WHERE e.id = (SELECT exam_id FROM exam_records WHERE id = ?)
              AND q.question_type IN ('multiple_choice', 'multiple_select', 'true_false')
        ''', (exam_record_id,)).fetchall()


def get_records_to_grade():
    with get_db() as conn:
        return conn.execute('''
            SELECT gr.*, q.question_text, u.username as student_name, e.title
            FROM grading_records gr
            JOIN questions q ON gr.question_id = q.id
            JOIN exam_records er ON gr.exam_record_id = er.id
            JOIN exams e ON er.exam_id = e.id
            JOIN users u ON er.student_id = u.id
            WHERE gr.teacher_score IS NULL
            ORDER BY e.id, u.username
        ''').fetchall()


def clear_grading_by_exam(conn, exam_id):
    conn.execute('''
        DELETE FROM grading_records
        WHERE exam_record_id IN (SELECT id FROM exam_records WHERE exam_id = ?)
    ''', (exam_id,))