import datetime
import json
import logging

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from utils.decorators import login_required, role_required
from utils.answer import is_answer_correct
from models.db import get_db
from models.question import (
    create_question, get_questions_by_teacher, get_question_by_id,
    update_question, delete_question, get_distinct_subjects,
    get_questions_filtered, update_explanation, get_questions_without_explanation
)
from models.exam import (
    create_exam, add_exam_question, get_exam_by_id, get_exams_by_teacher,
    get_exam_status, toggle_exam_status, get_exam_questions, delete_exam_cascade
)
from models.exam_record import get_exam_results_list, clear_exam_scores_cascade
from models.grading import (
    create_grading_record, update_grading_score, get_completed_gradings,
    get_objective_questions_for_record, get_records_to_grade, clear_grading_by_exam
)
from services.ai_service import ai_generate_questions, ai_generate_explanation

logger = logging.getLogger(__name__)

teacher_bp = Blueprint('teacher', __name__)


@teacher_bp.route('/add_question', methods=['GET', 'POST'], endpoint='add_question')
@login_required
@role_required('teacher')
def add_question():
    if request.method == 'POST':
        question_text = request.form['question_text']
        question_type = request.form['question_type']
        subject = request.form['subject']
        difficulty = request.form['difficulty']
        points = int(request.form.get('points', 1))
        explanation = request.form.get('explanation', '')

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
            correct_answer = request.form.get('correct_answer', '')
            test_cases = request.form.get('test_cases', '[]')
            solution_code = request.form.get('solution_code', '')
        else:
            option_a = option_b = option_c = option_d = option_e = option_f = None
            correct_answer = request.form.get('correct_answer', '')
            test_cases = None
            solution_code = None

        with get_db() as conn:
            create_question(conn, session['user_id'], question_text, option_a, option_b,
                            option_c, option_d, option_e, option_f, correct_answer,
                            question_type, subject, difficulty, points, test_cases,
                            solution_code, explanation)

        flash('题目添加成功', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('add_question.html')


@teacher_bp.route('/create_exam', methods=['GET', 'POST'], endpoint='create_exam')
@login_required
@role_required('teacher')
def create_exam():
    if request.method == 'POST':
        exam_name = request.form['exam_name']
        subject = request.form['subject']
        duration_minutes = int(request.form['duration_minutes'])
        anti_cheat_enabled = 'anti_cheat_enabled' in request.form
        shuffle_questions = 'shuffle_questions' in request.form

        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')

        start_time = None
        if start_time_str:
            dt_obj = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            start_time = dt_obj.strftime('%Y-%m-%d %H:%M:%S')

        end_time = None
        if end_time_str:
            dt_obj = datetime.datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
            end_time = dt_obj.strftime('%Y-%m-%d %H:%M:%S')

        with get_db() as conn:
            exam_id = create_exam(conn, exam_name, subject, session['user_id'],
                                  duration_minutes, start_time, end_time,
                                  anti_cheat_enabled, shuffle_questions)

            selected_questions = request.form.getlist('questions')
            for qid in selected_questions:
                add_exam_question(conn, exam_id, qid)
            conn.commit()

        flash('考试创建成功', 'success')
        return redirect(url_for('main.dashboard'))

    questions = get_questions_by_teacher(session['user_id'])
    return render_template('create_exam.html', questions=questions)


@teacher_bp.route('/manage_questions', endpoint='manage_questions')
@login_required
@role_required('teacher')
def manage_questions():
    filter_subject = request.args.get('subject', '')
    filter_type = request.args.get('question_type', '')

    subjects = get_distinct_subjects(session['user_id'])
    questions = get_questions_filtered(session['user_id'], filter_subject, filter_type)

    return render_template('manage_questions.html',
                           questions=questions,
                           subjects=subjects,
                           filter_subject=filter_subject,
                           filter_type=filter_type)


@teacher_bp.route('/edit_question/<int:question_id>', methods=['GET', 'POST'], endpoint='edit_question')
@login_required
@role_required('teacher')
def edit_question(question_id):
    question = get_question_by_id(question_id)
    if not question:
        flash('题目不存在！', 'error')
        return redirect(url_for('teacher.manage_questions'))
    if question['teacher_id'] != session['user_id']:
        flash('您没有权限编辑此题目！', 'error')
        return redirect(url_for('teacher.manage_questions'))

    if request.method == 'POST':
        question_text = request.form['question_text']
        subject = request.form['subject']
        difficulty = request.form['difficulty']
        explanation = request.form.get('explanation', '')
        q_type = question['question_type']

        if q_type in ['multiple_choice', 'multiple_select', 'true_false']:
            option_a = request.form.get('option_a', '')
            option_b = request.form.get('option_b', '')
            option_c = request.form.get('option_c', '')
            option_d = request.form.get('option_d', '')
            option_e = request.form.get('option_e', '')
            option_f = request.form.get('option_f', '')
            correct_answer = request.form.get('correct_answer', '')
            test_cases = question['test_cases']
            solution_code = question['solution_code']
        elif q_type == 'programming':
            option_a = question['option_a']
            option_b = question['option_b']
            option_c = question['option_c']
            option_d = question['option_d']
            option_e = question['option_e']
            option_f = question['option_f']
            correct_answer = request.form.get('correct_answer', '')
            test_cases = request.form.get('test_cases', '[]')
            solution_code = request.form.get('solution_code', '')
        else:
            option_a = question['option_a']
            option_b = question['option_b']
            option_c = question['option_c']
            option_d = question['option_d']
            option_e = question['option_e']
            option_f = question['option_f']
            correct_answer = request.form.get('correct_answer', '')
            test_cases = question['test_cases']
            solution_code = question['solution_code']

        with get_db() as conn:
            update_question(conn, question_id, question_text, option_a, option_b,
                            option_c, option_d, option_e, option_f, correct_answer,
                            subject, difficulty, test_cases, solution_code, explanation)
        flash('题目已更新！', 'success')
        return redirect(url_for('teacher.manage_questions'))

    return render_template('edit_question.html', question=question)


@teacher_bp.route('/delete_question/<int:question_id>', methods=['POST'], endpoint='delete_question')
@login_required
@role_required('teacher')
def delete_question_route(question_id):
    with get_db() as conn:
        question = get_question_by_id(question_id)
        if not question:
            flash('题目不存在！', 'error')
            return redirect(url_for('teacher.manage_questions'))
        if question['teacher_id'] != session['user_id']:
            flash('您没有权限删除此题目！', 'error')
            return redirect(url_for('teacher.manage_questions'))
        delete_question(conn, question_id)
    flash('题目已删除！', 'success')
    return redirect(url_for('teacher.manage_questions'))


@teacher_bp.route('/generate_explanation/<int:question_id>', methods=['POST'], endpoint='generate_explanation')
@login_required
@role_required('teacher')
def generate_explanation_route(question_id):
    question = get_question_by_id(question_id)
    if not question:
        flash('题目不存在！', 'error')
        return redirect(url_for('teacher.manage_questions'))
    if question['teacher_id'] != session['user_id']:
        flash('您没有权限操作此题目！', 'error')
        return redirect(url_for('teacher.manage_questions'))

    explanation, error = ai_generate_explanation(question)
    if error:
        flash(f'AI 生成解析失败: {error}', 'error')
    else:
        with get_db() as conn:
            update_explanation(conn, question_id, explanation)
        flash('解析已生成！', 'success')

    return redirect(url_for('teacher.manage_questions'))


@teacher_bp.route('/generate_all_explanations', methods=['POST'], endpoint='generate_all_explanations')
@login_required
@role_required('teacher')
def generate_all_explanations():
    questions = get_questions_without_explanation(session['user_id'])

    if not questions:
        flash('没有需要生成解析的题目（所有题目已有解析）', 'info')
        return redirect(url_for('teacher.manage_questions'))

    success_count = 0
    for q in questions:
        question = get_question_by_id(q['id'])
        if not question:
            continue
        explanation, error = ai_generate_explanation(question)
        if error:
            logger.error(f"批量生成解析 - 题目 {q['id']} 失败: {error}")
            continue
        with get_db() as conn:
            update_explanation(conn, q['id'], explanation)
        success_count += 1

    flash(f'批量生成完成！成功 {success_count}/{len(questions)} 题', 'success')
    return redirect(url_for('teacher.manage_questions'))


@teacher_bp.route('/toggle_exam_status/<int:exam_id>', methods=['POST'], endpoint='toggle_exam_status')
@login_required
@role_required('teacher')
def toggle_exam_status_route(exam_id):
    try:
        exam = get_exam_status(exam_id)
        if exam:
            new_status = 'inactive' if exam['status'] == 'active' else 'active'
            with get_db() as conn:
                toggle_exam_status(conn, exam_id, new_status)
            status_text = '禁用' if new_status == 'inactive' else '启用'
            flash(f'考试已{status_text}！', 'success')
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        flash(f'操作失败: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))


@teacher_bp.route('/exam_results/<int:exam_id>', endpoint='exam_results')
@login_required
@role_required('teacher')
def exam_results(exam_id):
    exam = get_exam_by_id(exam_id)
    results = get_exam_results_list(exam_id)

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


@teacher_bp.route('/grade_subjective_questions', methods=['GET', 'POST'], endpoint='grade_subjective_questions')
@login_required
@role_required('teacher')
def grade_subjective_questions():
    if request.method == 'POST':
        with get_db() as conn:
            for key, value in request.form.items():
                if key.startswith('score_'):
                    grading_record_id = key.split('_')[1]
                    score = int(value)
                    update_grading_score(conn, grading_record_id, score, session['user_id'])

            completed_gradings = get_completed_gradings()

            for record in completed_gradings:
                exam_record_id = record['exam_record_id']

                exam_record_data = conn.execute(
                    'SELECT answers FROM exam_records WHERE id = ?', (exam_record_id,)
                ).fetchone()
                student_answers = json.loads(exam_record_data['answers']) if exam_record_data['answers'] else {}

                objective_questions = get_objective_questions_for_record(exam_record_id)

                objective_score = 0
                for q in objective_questions:
                    qid_str = str(q['id'])
                    if qid_str in student_answers:
                        student_answer = student_answers[qid_str]
                        if is_answer_correct(student_answer, q['correct_answer'], q['question_type']):
                            objective_score += q['points']

                total_score = objective_score + (record['subjective_score'] or 0)
                conn.execute('UPDATE exam_records SET score = ? WHERE id = ?',
                             (total_score, exam_record_id))

            conn.commit()

        flash('评分提交成功！', 'success')
        return redirect(url_for('main.dashboard'))

    records_to_grade = get_records_to_grade()
    return render_template('grade_subjective_questions.html', records_to_grade=records_to_grade)


@teacher_bp.route('/clear_exam_scores/<int:exam_id>', methods=['POST'], endpoint='clear_exam_scores')
@login_required
@role_required('teacher')
def clear_exam_scores(exam_id):
    try:
        with get_db() as conn:
            deleted_count = clear_exam_scores_cascade(conn, exam_id)
        flash(f'已清空 {deleted_count} 条考试成绩！', 'success')
    except Exception as e:
        logger.error(f"清空成绩失败: {e}")
        flash(f'清空成绩失败: {str(e)}', 'error')
    return redirect(url_for('teacher.exam_results', exam_id=exam_id))


@teacher_bp.route('/delete_exam/<int:exam_id>', methods=['POST'], endpoint='delete_exam')
@login_required
@role_required('teacher')
def delete_exam(exam_id):
    try:
        with get_db() as conn:
            delete_exam_cascade(conn, exam_id)
        flash('考试已成功删除！', 'success')
    except Exception as e:
        logger.error(f"删除考试失败: {e}")
        flash(f'删除考试失败: {str(e)}', 'error')
    return redirect(url_for('main.dashboard'))


@teacher_bp.route('/ai_generate', methods=['GET', 'POST'], endpoint='ai_generate')
@login_required
@role_required('teacher')
def ai_generate():
    if request.method == 'POST':
        topic = request.form['topic']
        difficulty = request.form['difficulty']
        num = int(request.form['num'])
        question_type = request.form.get('question_type', 'multiple_choice')

        questions_list, type_name, error = ai_generate_questions(topic, difficulty, num, question_type)

        if error:
            flash(error)
            return render_template('ai_generate.html')

        success_count = 0
        with get_db() as conn:
            for q in questions_list:
                q_text = q.get('question_text', q.get('question', ''))
                explanation = q.get('explanation', '')
                correct_ans = q.get('correct_answer', q.get('answer', ''))

                if question_type == 'multiple_choice':
                    create_question(conn, session['user_id'], q_text,
                                    q.get('option_a', ''), q.get('option_b', ''),
                                    q.get('option_c', ''), q.get('option_d', ''),
                                    None, None, correct_ans, question_type, topic,
                                    difficulty, 1, None, None, explanation)

                elif question_type == 'multiple_select':
                    create_question(conn, session['user_id'], q_text,
                                    q.get('option_a', ''), q.get('option_b', ''),
                                    q.get('option_c', ''), q.get('option_d', ''),
                                    q.get('option_e', ''), q.get('option_f', ''),
                                    correct_ans, question_type, topic, difficulty,
                                    1, None, None, explanation)

                elif question_type == 'true_false':
                    create_question(conn, session['user_id'], q_text,
                                    '正确', '错误', None, None, None, None,
                                    correct_ans, question_type, topic, difficulty,
                                    1, None, None, explanation)

                elif question_type == 'short_answer':
                    create_question(conn, session['user_id'], q_text,
                                    None, None, None, None, None, None,
                                    correct_ans, question_type, topic, difficulty,
                                    1, None, None, explanation)

                elif question_type == 'programming':
                    test_cases = q.get('test_cases', '[]')
                    solution_code = q.get('solution_code', correct_ans)
                    create_question(conn, session['user_id'], q_text,
                                    None, None, None, None, None, None,
                                    correct_ans, question_type, topic, difficulty,
                                    1, test_cases, solution_code, explanation)

                else:
                    create_question(conn, session['user_id'], q_text,
                                    None, None, None, None, None, None,
                                    correct_ans, question_type, topic, difficulty,
                                    1, None, None, explanation)

                success_count += 1
            conn.commit()
        flash(f'成功生成并导入 {success_count} 道{type_name}！')

    return render_template('ai_generate.html')