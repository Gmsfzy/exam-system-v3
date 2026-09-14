def is_answer_correct(student_answer, correct_answer, question_type):
    if question_type in ['multiple_choice', 'true_false']:
        return student_answer.upper() == correct_answer.upper()
    elif question_type == 'multiple_select':
        student_answers = set(student_answer.upper().split(','))
        correct_answers = set(correct_answer.upper().split(','))
        return student_answers == correct_answers
    elif question_type in ['short_answer', 'programming']:
        return False
    return False