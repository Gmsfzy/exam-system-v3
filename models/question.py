from models.db import get_db


def create_question(conn, teacher_id, question_text, option_a, option_b, option_c,
                    option_d, option_e, option_f, correct_answer, question_type,
                    subject, difficulty, points, test_cases, solution_code, explanation):
    conn.execute('''
        INSERT INTO questions (teacher_id, question_text, option_a, option_b, option_c, option_d,
                               option_e, option_f, correct_answer, question_type, subject,
                               difficulty, points, test_cases, solution_code, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (teacher_id, question_text, option_a, option_b, option_c, option_d, option_e, option_f,
          correct_answer, question_type, subject, difficulty, points, test_cases, solution_code, explanation))
    conn.commit()


def get_questions_by_teacher(teacher_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM questions WHERE teacher_id = ? ORDER BY created_at DESC',
            (teacher_id,)
        ).fetchall()


def get_question_by_id(question_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM questions WHERE id = ?', (question_id,)
        ).fetchone()


def update_question(conn, question_id, question_text, option_a, option_b, option_c,
                    option_d, option_e, option_f, correct_answer, subject, difficulty,
                    test_cases, solution_code, explanation):
    conn.execute('''
        UPDATE questions SET question_text=?, option_a=?, option_b=?, option_c=?, option_d=?,
                             option_e=?, option_f=?, correct_answer=?, subject=?, difficulty=?,
                             test_cases=?, solution_code=?, explanation=?
        WHERE id = ?
    ''', (question_text, option_a, option_b, option_c, option_d, option_e, option_f,
          correct_answer, subject, difficulty, test_cases, solution_code, explanation,
          question_id))
    conn.commit()


def delete_question(conn, question_id):
    conn.execute('DELETE FROM questions WHERE id = ?', (question_id,))
    conn.commit()


def get_distinct_subjects(teacher_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT DISTINCT subject FROM questions WHERE teacher_id = ? AND subject IS NOT NULL AND subject != "" ORDER BY subject',
            (teacher_id,)
        ).fetchall()


def get_questions_filtered(teacher_id, filter_subject='', filter_type=''):
    with get_db() as conn:
        query = 'SELECT * FROM questions WHERE teacher_id = ?'
        params = [teacher_id]
        if filter_subject:
            query += ' AND subject = ?'
            params.append(filter_subject)
        if filter_type:
            query += ' AND question_type = ?'
            params.append(filter_type)
        query += ' ORDER BY id DESC'
        return conn.execute(query, params).fetchall()


def update_explanation(conn, question_id, explanation):
    conn.execute('UPDATE questions SET explanation = ? WHERE id = ?', (explanation, question_id))
    conn.commit()


def get_questions_without_explanation(teacher_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT id FROM questions WHERE teacher_id = ? AND (explanation IS NULL OR explanation = "")',
            (teacher_id,)
        ).fetchall()