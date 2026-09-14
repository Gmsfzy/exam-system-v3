"""
在线考试系统 v3.0
架构：Flask Blueprints + 分层架构
  - config.py        配置集中管理
  - models/          数据层（所有 SQL 隔离）
  - routes/          路由层（按角色拆分蓝图）
  - services/        业务服务层（AI / 评测）
  - utils/           工具层（装饰器 / 答案判断）
"""

import logging
from flask import Flask

from config import Config
from models.db import init_db
from routes.auth import auth_bp
from routes.main import main_bp
from routes.teacher import teacher_bp
from routes.student import student_bp
from routes.common import common_bp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def create_app():
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(common_bp)

    init_db()

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)