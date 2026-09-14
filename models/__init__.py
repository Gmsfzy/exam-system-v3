from models.db import get_db, get_db_connection, init_db
from models.user import create_user, get_user_by_username, get_user_role
from models.question import (
    create_question, get_questions_by_teacher, get_question_by_id,
    update_question, delete_question, get_distinct_subjects,
    get_questions_filtered, update_explanation, get_questions_without_explanation
)
from models.exam import (
    create_exam, get_exam_by_id, get_exams_by_teacher, get_exam_status,
    toggle_exam_status, add_exam_question, get_exam_questions,
    get_active_exams, get_upcoming_exams, get_completed_exams, delete_exam_cascade
)
from models.exam_record import (
    create_exam_record, get_exam_record_by_id, get_in_progress_record,
    update_exam_record_submit, get_anti_cheat_logs, update_anti_cheat_logs,
    get_pending_grading_records, get_exam_results_list, clear_exam_scores_cascade,
    get_student_record_with_answer, get_exam_questions_for_result, get_grading_map
)
from models.grading import (
    create_grading_record, update_grading_score, get_completed_gradings,
    get_objective_questions_for_record, get_records_to_grade, clear_grading_by_exam
)
from models.image import create_image_attachment, get_image_attachment_by_id