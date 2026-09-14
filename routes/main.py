import datetime

from flask import Blueprint, render_template, redirect, url_for, session

from utils.decorators import login_required
from models.exam import get_exams_by_teacher, get_active_exams, get_upcoming_exams, get_completed_exams
from models.question import get_questions_by_teacher
from models.exam_record import get_pending_grading_records

main_bp = Blueprint('main', __name__)


@main_bp.route('/', endpoint='index')
def index():
    return render_template('index.html')


@main_bp.route('/dashboard', endpoint='dashboard')
@login_required
def dashboard():
    if session['role'] == 'teacher':
        exams = get_exams_by_teacher(session['user_id'])
        questions = get_questions_by_teacher(session['user_id'])
        pending_grading = get_pending_grading_records()
        return render_template('teacher_dashboard.html', exams=exams, questions=questions, pending_grading=pending_grading)

    elif session['role'] == 'student':
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user_id = session['user_id']
        current_exams = get_active_exams(current_time, user_id)
        upcoming_exams = get_upcoming_exams(current_time, user_id)
        completed_exams = get_completed_exams(user_id)
        return render_template('student_dashboard.html',
                               current_exams=current_exams,
                               upcoming_exams=upcoming_exams,
                               completed_exams=completed_exams)