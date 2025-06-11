from flask import request, jsonify
import pandas as pd
from io import StringIO
import json
from datetime import datetime
import logging

from .task20_evaluator import evaluate_task20
from database import db, Task20Result

logger = logging.getLogger(__name__)


def handle_task20_check():
    """
    Обработчик для проверки одного задания 20
    
    Expects JSON:
    {
        "task_text": "текст задания",
        "student_answer": "ответ ученика",
        "student_id": "ID ученика (опционально)"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        task_text = data.get('task_text', '').strip()
        student_answer = data.get('student_answer', '').strip()
        student_id = data.get('student_id', 'anonymous')
        
        if not task_text or not student_answer:
            return jsonify({"error": "Both task_text and student_answer are required"}), 400
        
        # Выполняем проверку
        result = evaluate_task20(task_text, student_answer)
        
        # Сохраняем результат в базу данных
        try:
            task20_result = Task20Result(
                student_id=student_id,
                task_text=task_text,
                student_answer=student_answer,
                score=result.get('score', 0),
                max_score=result.get('max_score', 3),
                required_arguments=result.get('required_arguments', 0),
                valid_arguments_count=result.get('valid_arguments_count', 0),
                evaluation_details=json.dumps(result, ensure_ascii=False),
                created_at=datetime.utcnow()
            )
            db.session.add(task20_result)
            db.session.commit()
            
            result['result_id'] = task20_result.id
            
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            # Продолжаем работу даже если не удалось сохранить в БД
            result['warning'] = "Failed to save to database"
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in handle_task20_check: {str(e)}")
        return jsonify({"error": str(e)}), 500


def handle_task20_bulk_check():
    """
    Обработчик для массовой проверки заданий 20
    
    Expects multipart/form-data with CSV file
    CSV format:
    student_id,task_text,student_answer
    """
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
            
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "Only CSV files are supported"}), 400
        
        # Читаем CSV
        csv_content = file.read().decode('utf-8')
        df = pd.read_csv(StringIO(csv_content))
        
        # Проверяем наличие необходимых колонок
        required_columns = ['student_id', 'task_text', 'student_answer']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return jsonify({
                "error": f"Missing required columns: {', '.join(missing_columns)}"
            }), 400
        
        results = []
        errors = []
        
        # Обрабатываем каждую строку
        for index, row in df.iterrows():
            try:
                student_id = str(row['student_id']).strip()
                task_text = str(row['task_text']).strip()
                student_answer = str(row['student_answer']).strip()
                
                if not task_text or not student_answer:
                    errors.append({
                        "row": index + 1,
                        "student_id": student_id,
                        "error": "Empty task_text or student_answer"
                    })
                    continue
                
                # Выполняем проверку
                result = evaluate_task20(task_text, student_answer)
                result['student_id'] = student_id
                result['row'] = index + 1
                
                # Сохраняем в базу данных
                try:
                    task20_result = Task20Result(
                        student_id=student_id,
                        task_text=task_text,
                        student_answer=student_answer,
                        score=result.get('score', 0),
                        max_score=result.get('max_score', 3),
                        required_arguments=result.get('required_arguments', 0),
                        valid_arguments_count=result.get('valid_arguments_count', 0),
                        evaluation_details=json.dumps(result, ensure_ascii=False),
                        created_at=datetime.utcnow()
                    )
                    db.session.add(task20_result)
                    
                except Exception as e:
                    logger.error(f"Database error for row {index + 1}: {str(e)}")
                
                results.append(result)
                
            except Exception as e:
                errors.append({
                    "row": index + 1,
                    "student_id": row.get('student_id', 'unknown'),
                    "error": str(e)
                })
        
        # Коммитим все изменения в БД
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"Database commit error: {str(e)}")
        
        # Подготавливаем сводку
        summary = {
            "total_processed": len(results) + len(errors),
            "successful": len(results),
            "failed": len(errors),
            "average_score": sum(r['score'] for r in results) / len(results) if results else 0,
            "score_distribution": {}
        }
        
        # Считаем распределение оценок
        for score in range(4):
            summary['score_distribution'][str(score)] = len([r for r in results if r['score'] == score])
        
        return jsonify({
            "summary": summary,
            "results": results,
            "errors": errors
        }), 200
        
    except Exception as e:
        logger.error(f"Error in handle_task20_bulk_check: {str(e)}")
        return jsonify({"error": str(e)}), 500


def handle_task20_statistics():
    """
    Обработчик для получения статистики по заданию 20
    
    Query parameters:
    - student_id: фильтр по ID ученика
    - date_from: начальная дата (YYYY-MM-DD)
    - date_to: конечная дата (YYYY-MM-DD)
    """
    try:
        # Строим запрос
        query = Task20Result.query
        
        # Применяем фильтры
        student_id = request.args.get('student_id')
        if student_id:
            query = query.filter_by(student_id=student_id)
            
        date_from = request.args.get('date_from')
        if date_from:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Task20Result.created_at >= date_from)
            
        date_to = request.args.get('date_to')
        if date_to:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
            query = query.filter(Task20Result.created_at <= date_to)
        
        results = query.all()
        
        if not results:
            return jsonify({
                "total_attempts": 0,
                "average_score": 0,
                "score_distribution": {str(i): 0 for i in range(4)},
                "average_arguments_ratio": 0
            }), 200
        
        # Подсчитываем статистику
        total_score = sum(r.score for r in results)
        score_distribution = {str(i): 0 for i in range(4)}
        
        total_valid_args = 0
        total_required_args = 0
        
        for result in results:
            score_distribution[str(result.score)] += 1
            total_valid_args += result.valid_arguments_count
            total_required_args += result.required_arguments
        
        statistics = {
            "total_attempts": len(results),
            "average_score": total_score / len(results),
            "score_distribution": score_distribution,
            "average_arguments_ratio": total_valid_args / total_required_args if total_required_args > 0 else 0,
            "filters_applied": {
                "student_id": student_id,
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None
            }
        }
        
        # Добавляем детальную информацию по типам ошибок
        error_analysis = {
            "no_generalization": 0,
            "concrete_examples": 0,
            "wrong_type": 0,
            "too_short": 0
        }
        
        for result in results:
            try:
                details = json.loads(result.evaluation_details)
                for arg in details.get('invalid_arguments', []):
                    reason = arg.get('reason', '').lower()
                    if 'обобщен' in reason:
                        error_analysis['no_generalization'] += 1
                    elif 'конкретн' in reason:
                        error_analysis['concrete_examples'] += 1
                    elif 'тип' in reason:
                        error_analysis['wrong_type'] += 1
                    elif 'коротк' in reason:
                        error_analysis['too_short'] += 1
            except:
                continue
        
        statistics['error_analysis'] = error_analysis
        
        return jsonify(statistics), 200
        
    except Exception as e:
        logger.error(f"Error in handle_task20_statistics: {str(e)}")
        return jsonify({"error": str(e)}), 500


def handle_task20_export():
    """
    Обработчик для экспорта результатов в CSV
    
    Expects JSON:
    {
        "student_ids": ["id1", "id2", ...] или null для всех,
        "date_from": "YYYY-MM-DD" или null,
        "date_to": "YYYY-MM-DD" или null
    }
    """
    try:
        data = request.get_json()
        
        # Строим запрос
        query = Task20Result.query
        
        # Применяем фильтры
        if data.get('student_ids'):
            query = query.filter(Task20Result.student_id.in_(data['student_ids']))
            
        if data.get('date_from'):
            date_from = datetime.strptime(data['date_from'], '%Y-%m-%d')
            query = query.filter(Task20Result.created_at >= date_from)
            
        if data.get('date_to'):
            date_to = datetime.strptime(data['date_to'], '%Y-%m-%d')
            query = query.filter(Task20Result.created_at <= date_to)
        
        results = query.all()
        
        # Подготавливаем данные для экспорта
        export_data = []
        for result in results:
            try:
                details = json.loads(result.evaluation_details)
                valid_args = details.get('valid_arguments', [])
                invalid_args = details.get('invalid_arguments', [])
                
                export_data.append({
                    'student_id': result.student_id,
                    'date': result.created_at.isoformat(),
                    'score': result.score,
                    'max_score': result.max_score,
                    'required_arguments': result.required_arguments,
                    'valid_arguments_count': result.valid_arguments_count,
                    'task_text': result.task_text[:100] + '...' if len(result.task_text) > 100 else result.task_text,
                    'valid_arguments': '; '.join([arg['text'] for arg in valid_args]),
                    'invalid_arguments': '; '.join([f"{arg['text']} ({arg['reason']})" for arg in invalid_args]),
                    'comment': details.get('comment', '')
                })
            except:
                continue
        
        # Создаем DataFrame и конвертируем в CSV
        df = pd.DataFrame(export_data)
        csv_string = df.to_csv(index=False)
        
        return csv_string, 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': f'attachment; filename=task20_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        }
        
    except Exception as e:
        logger.error(f"Error in handle_task20_export: {str(e)}")
        return jsonify({"error": str(e)}), 500