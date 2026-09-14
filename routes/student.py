import datetime
import json
import base64
import secrets
import logging

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from utils.decorators import login_required, role_required
from utils.answer import is_answer_correct
from models.db import get_db
from models.exam import get_exam_by_id, get_exam_questions
from models.exam_record import (
    create_exam_record, get_exam_record_by_id, get_in_progress_record,
    update_exam_record_submit, detect_cheating, get_student_record_with_answer,
    get_exam_questions_for_result, get_grading_map
)
from models.grading import create_grading_record
from models.image import create_image_attachment
from services.ai_service import grade_short_answer_ai
from services.evaluator import evaluate_programming_solution

logger = logging.getLogger(__name__)

student_bp = Blueprint('student', __name__)


@student_bp.route('/take_exam/<int:exam_id>', endpoint='take_exam')
@login_required
@role_required('student')
def take_exam(exam_id):
    exam = get_exam_by_id(exam_id)
    if not exam:
        flash('考试不存在', 'error')
        return redirect(url_for('main.dashboard'))

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if exam['start_time'] and now_str < exam['start_time']:
        flash('考试尚未开始', 'error')
        return redirect(url_for('main.dashboard'))

    if exam['end_time'] and now_str > exam['end_time']:
        flash('考试已结束', 'error')
        return redirect(url_for('main.dashboard'))

    questions = get_exam_questions(exam_id, shuffle=exam['shuffle_questions'])

    existing_record = get_in_progress_record(exam_id, session['user_id'])

    with get_db() as conn:
        if existing_record:
            record_id = existing_record['id']
        else:
            start_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            record_id = create_exam_record(conn, exam_id, session['user_id'], start_time)
            conn.commit()

    return render_template('take_exam.html',
                           exam=exam,
                           questions=questions,
                           record_id=record_id,
                           anti_cheat_enabled=exam['anti_cheat_enabled'])


@student_bp.route('/submit_exam/<int:record_id>', methods=['POST'], endpoint='submit_exam')
@login_required
@role_required('student')
def submit_exam(record_id):
    answers = {}
    images = {}

    for key, value in request.form.items():
        if key.startswith('question_'):
            question_id = key.split('_')[1]
            answers[question_id] = value
        elif key.startswith('image_'):
            question_id = key.split('_')[1]
            images[question_id] = value

    with get_db() as conn:
        record = get_exam_record_by_id(record_id)
        if not record or record['status'] != 'in_progress':
            flash('无效的考试记录', 'error')
            return redirect(url_for('main.dashboard'))

        exam = get_exam_by_id(record['exam_id'])
        questions = get_exam_questions(record['exam_id'])

        score = 0
        total_questions = len(questions)
        subjective_questions = []
        programming_questions = []

        for question in questions:
            question_id = str(question['id'])
            if question_id in answers:
                answer = answers[question_id]

                if question['question_type'] in ['multiple_choice', 'true_false']:
                    if is_answer_correct(answer, question['correct_answer'], question['question_type']):
                        score += question['points']
                elif question['question_type'] == 'multiple_select':
                    student_answers_set = set(answer.upper().split(',')) if answer else set()
                    correct_answers_set = set(question['correct_answer'].upper().split(','))
                    if student_answers_set == correct_answers_set:
                        score += question['points']
                elif question['question_type'] == 'programming':
                    if question['test_cases']:
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
                        subjective_questions.append({
                            'question_id': question['id'],
                            'answer': answer,
                            'points': question['points']
                        })
                elif question['question_type'] == 'short_answer':
                    student_answer = answers.get(question_id, "")
                    if not student_answer.strip():
                        create_grading_record(conn, record_id, question['id'], '',
                                              teacher_score=0, max_score=question['points'], grader_id=-1)
                        continue

                    standard_hint = question['correct_answer']
                    ai_raw_score, ai_comment = grade_short_answer_ai(
                        question['question_text'], standard_hint, student_answer
                    )

                    max_points = question['points']

                    if ai_raw_score is None:
                        subjective_questions.append({
                            'question_id': question['id'],
                            'answer': student_answer,
                            'points': question['points']
                        })
                        continue

                    actual_score = int((ai_raw_score / 10) * max_points)
                    score += actual_score
                    create_grading_record(conn, record_id, question['id'], student_answer,
                                          teacher_score=actual_score, max_score=max_points, grader_id=-1)

        submit_time = datetime.datetime.now()
        has_manual_grading = bool(subjective_questions or any(q['auto_score'] < q['max_score'] for q in programming_questions))
        final_score = score if not has_manual_grading else None

        update_exam_record_submit(conn, record_id, submit_time, final_score, total_questions, json.dumps(answers))

        for subj_q in subjective_questions:
            create_grading_record(conn, record_id, subj_q['question_id'], subj_q['answer'],
                                  max_score=subj_q['points'])

        for prog_q in programming_questions:
            create_grading_record(conn, record_id, prog_q['question_id'], prog_q['answer'],
                                  auto_score=prog_q['auto_score'], max_score=prog_q['max_score'])

        for qid, img_data in images.items():
            if img_data:
                header, encoded = img_data.split(',', 1)
                image_data = base64.b64decode(encoded)
                filename = f"{secrets.token_hex(8)}.png"
                create_image_attachment(conn, qid, record_id, filename, image_data)

        conn.commit()

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
        flash(f'考试提交成功！{"。 ".join(feedback_parts)}。', 'success')
    else:
        flash(f'考试提交成功！您的得分是 {score} 分', 'success')

    return redirect(url_for('student.view_exam_result', record_id=record_id))


@student_bp.route('/exam_result/<int:record_id>', endpoint='view_exam_result')
@login_required
@role_required('student')
def view_exam_result(record_id):
    record = get_student_record_with_answer(record_id, session['user_id'])
    if not record:
        flash('未找到考试记录或无权访问', 'error')
        return redirect(url_for('main.dashboard'))

    student_answers = json.loads(record['answers']) if record['answers'] else {}

    with get_db() as conn:
        exam = conn.execute('SELECT status, end_time FROM exams WHERE id = ?', (record['exam_id'],)).fetchone()

    show_explanation = False
    if exam:
        if exam['status'] == 'inactive':
            show_explanation = True
        elif exam['end_time']:
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if now_str >= exam['end_time']:
                show_explanation = True

    questions = get_exam_questions_for_result(record['exam_id'])

    subjective_ids = [q['id'] for q in questions if q['question_type'] in ('short_answer', 'programming')]
    grading_map = get_grading_map(record_id, subjective_ids)

    return render_template(
        'exam_result.html',
        record=record,
        questions=questions,
        student_answers=student_answers,
        grading_map=grading_map,
        show_explanation=show_explanation
    )


@student_bp.route('/cheating_detected/<int:record_id>', methods=['POST'], endpoint='cheating_detected')
@login_required
@role_required('student')
def cheating_detected(record_id):
    data = request.json
    action = data.get('action')
    details = data.get('details')
    detect_cheating(record_id, action, details)
    return jsonify({'status': 'logged'})