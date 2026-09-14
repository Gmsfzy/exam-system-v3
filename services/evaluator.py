import json
import subprocess
import tempfile
import os
import sys
import logging

logger = logging.getLogger(__name__)


def evaluate_programming_solution(student_code, test_cases_json, reference_solution=None):
    try:
        test_cases = json.loads(test_cases_json)
        passed = 0
        total = len(test_cases)

        restricted_env = {
            'PATH': os.environ.get('PATH', ''),
            'PYTHONIOENCODING': 'utf-8',
        }

        for case in test_cases:
            input_data = case.get('input', '')
            expected_output = case.get('expected_output', '').strip()

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(student_code)
                temp_file_name = temp_file.name

            try:
                result = subprocess.run(
                    [sys.executable, '-S', '-u', temp_file_name],
                    input=input_data,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=restricted_env,
                )
                output = result.stdout.strip()

                if output == expected_output:
                    passed += 1
                elif result.returncode != 0:
                    logger.debug(f"编程题评测运行错误: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                logger.warning(f"编程题评测超时: 测试用例期望输出 '{expected_output}'")
            except Exception as e:
                logger.error(f"编程题评测执行异常: {e}")
            finally:
                try:
                    os.unlink(temp_file_name)
                except OSError:
                    pass

        return passed, total
    except Exception as e:
        logger.error(f"编程题评测异常: {e}")
        return 0, len(json.loads(test_cases_json)) if test_cases_json else 0