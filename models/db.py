import sqlite3
import logging
from contextlib import contextmanager

from config import Config

logger = logging.getLogger(__name__)


def get_db_connection():
    conn = sqlite3.connect(Config.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(Config.DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

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
            correct_answer TEXT,
            question_type TEXT DEFAULT 'multiple_choice',
            subject TEXT,
            difficulty TEXT,
            points INTEGER DEFAULT 1,
            test_cases TEXT,
            solution_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            subject TEXT,
            teacher_id INTEGER NOT NULL,
            duration_minutes INTEGER,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            status TEXT DEFAULT 'inactive',
            anti_cheat_enabled BOOLEAN DEFAULT 0,
            shuffle_questions BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            FOREIGN KEY (exam_id) REFERENCES exams(id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            start_time TIMESTAMP,
            submit_time TIMESTAMP,
            score INTEGER,
            total_questions INTEGER,
            answers TEXT,
            status TEXT DEFAULT 'in_progress',
            anti_cheat_logs TEXT,
            FOREIGN KEY (exam_id) REFERENCES exams(id),
            FOREIGN KEY (student_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS grading_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_record_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            student_answer TEXT,
            teacher_score INTEGER,
            auto_score INTEGER,
            max_score INTEGER,
            grader_id INTEGER,
            graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_record_id) REFERENCES exam_records(id),
            FOREIGN KEY (question_id) REFERENCES questions(id),
            FOREIGN KEY (grader_id) REFERENCES users(id)
        )
    ''')

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

    try:
        conn.execute("ALTER TABLE exams ADD COLUMN status TEXT DEFAULT 'inactive'")
        conn.commit()
        logger.info("数据库已更新：添加了 status 列")
    except Exception as e:
        if "duplicate column name" in str(e):
            pass
        else:
            logger.warning(f"数据库检查出现其他错误: {e}")
    finally:
        conn.close()

    conn2 = sqlite3.connect(Config.DB_NAME)
    try:
        conn2.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
        conn2.commit()
        logger.info("数据库已更新：添加了 explanation 列")
    except Exception as e:
        if "duplicate column name" in str(e):
            pass
        else:
            logger.warning(f"数据库检查出现其他错误: {e}")
    finally:
        conn2.close()