from flask import Blueprint, session

from utils.decorators import login_required
from models.image import get_image_attachment_by_id

common_bp = Blueprint('common', __name__)


@common_bp.route('/image_attachment/<int:attachment_id>', endpoint='get_image_attachment')
@login_required
def get_image_attachment(attachment_id):
    from flask import current_app
    attachment = get_image_attachment_by_id(attachment_id)
    if not attachment:
        return '', 404
    response = current_app.response_class(
        response=attachment['data'],
        status=200,
        mimetype='image/png'
    )
    return response