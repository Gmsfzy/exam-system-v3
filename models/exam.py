from models.db import get_db


def create_exam(conn, title, subject, teacher_id, duration_minutes, start_time, end_time,
                anti_cheat_enabled, shuffle_questions):
    conn.execute('''
        INSERT INTO exams (title, subject, teacher_id, duration_minutes, start_time, end_time,
                           anti_cheat_enabled, shuffle_questions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (title, subject, teacher_id, duration_minutes, start_time, end_time,
          anti_cheat_enabled, shuffle_questions))
    exam_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    return exam_id


def add_exam_question(conn, exam_id, question_id):
    conn.execute('INSERT INTO exam_questions (exam_id, question_id) VALUES (?, ?)',
                 (exam_id, question_id))


def get_exam_by_id(exam_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()


def get_exams_by_teacher(teacher_id):
    with get_db() as conn:
        return conn.execute(
            'SELECT e.*, COUNT(eq.id) as question_count FROM exams e '
            'LEFT JOIN exam_questions eq ON e.id = eq.exam_id '
            'WHERE e.teacher_id = ? GROUP BY e.id ORDER BY e.created_at DESC',
            (teacher_id,)
        ).fetchall()


def get_exam_status(exam_id):
    with get_db() as conn:
        return conn.execute('SELECT status FROM exams WHERE id = ?', (exam_id,)).fetchone()


def toggle_exam_status(conn, exam_id, new_status):
    conn.execute('UPDATE exams SET status = ? WHERE id = ?', (new_status, exam_id))
    conn.commit()


def get_exam_questions(exam_id, shuffle=False):
    with get_db() as conn:
        query = '''
            SELECT q.* FROM questions q
            JOIN exam_questions eq ON q.id = eq.question_id
            WHERE eq.exam_id = ?
        '''
        if shuffle:
            query += ' ORDER BY RANDOM()'
        else:
            query += ' ORDER BY q.id'
        return conn.execute(query, (exam_id,)).fetchall()


def get_active_exams(current_time, user_id):
    with get_db() as conn:
        return conn.execute(
            '''SELECT e.id, e.title, e.subject, e.start_time, e.end_time, e.status, u.username as teacher_name
               FROM exams e
               INNER JOIN users u ON e.teacher_id = u.id
               WHERE e.status = 'active'
                 AND (e.start_time IS NULL OR e.start_time <= :ct)
                 AND (e.end_time IS NULL OR e.end_time >= :ct)
                 AND e.id NOT IN (SELECT exam_id
                                  FROM exam_records
                                  WHERE student_id = :uid
                                    AND status = 'submitted')''',
            {"ct": current_time, "uid": user_id}
        ).fetchall()


def get_upcoming_exams(current_time, user_id):
    with get_db() as conn:
        return conn.execute(
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


def get_completed_exams(user_id):
    with get_db() as conn:
        return conn.execute(
            '''SELECT er.*, e.title AS exam_name, u.username as teacher_name
               FROM exam_records er
               JOIN exams e ON er.exam_id = e.id
               JOIN users u ON e.teacher_id = u.id
               WHERE er.student_id = :uid
               ORDER BY er.id DESC''',
            {"uid": user_id}
        ).fetchall()


def delete_exam_cascade(conn, exam_id):
    conn.execute('''
        DELETE FROM grading_records
        WHERE exam_record_id IN (SELECT id FROM exam_records WHERE exam_id = ?)
    ''', (exam_id,))
    conn.execute('DELETE FROM exam_records WHERE exam_id = ?', (exam_id,))
    conn.execute('DELETE FROM exam_questions WHERE exam_id = ?', (exam_id,))
    conn.execute('DELETE FROM exams WHERE id = ?', (exam_id,))
    conn.commit()