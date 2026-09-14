from models.db import get_db


def create_image_attachment(conn, question_id, exam_record_id, filename, data):
    conn.execute('''
        INSERT INTO image_attachments (question_id, exam_record_id, filename, data)
        VALUES (?, ?, ?, ?)
    ''', (question_id, exam_record_id, filename, data))


def get_image_attachment_by_id(attachment_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM image_attachments WHERE id = ?', (attachment_id,)).fetchone()