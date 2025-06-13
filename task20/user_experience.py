"""Улучшения пользовательского опыта."""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class UserProgress:
    """Класс для отслеживания прогресса пользователя."""
    
    def __init__(self, user_data: dict):
        self.results = user_data.get('task20_results', [])
        self.achievements = user_data.get('task20_achievements', set())
        self.last_topic_id = user_data.get('task20_last_topic_id')
        self.session_start = user_data.get('task20_session_start')
    
    def get_stats(self) -> Dict:
        """Получить статистику пользователя."""
        if not self.results:
            return {
                'total_attempts': 0,
                'average_score': 0,
                'best_score': 0,
                'worst_score': 0,
                'unique_topics': 0,
                'total_time': 0,
                'streak': 0,
                'trend': 'neutral'
            }
        
        scores = [r['score'] for r in self.results]
        unique_topics = len(set(r['topic_id'] for r in self.results))
        
        # Тренд последних 5 попыток
        recent_scores = scores[-5:] if len(scores) >= 5 else scores
        if len(recent_scores) >= 2:
            trend = 'up' if recent_scores[-1] > recent_scores[0] else 'down' if recent_scores[-1] < recent_scores[0] else 'neutral'
        else:
            trend = 'neutral'
        
        # Стрик правильных ответов
        streak = 0
        for score in reversed(scores):
            if score >= 2:
                streak += 1
            else:
                break
        
        return {
            'total_attempts': len(self.results),
            'average_score': sum(scores) / len(scores),
            'best_score': max(scores),
            'worst_score': min(scores),
            'unique_topics': unique_topics,
            'total_time': self._calculate_total_time(),
            'streak': streak,
            'trend': trend
        }
    
    def _calculate_total_time(self) -> int:
        """Подсчёт общего времени в минутах."""
        if not self.results:
            return 0
        
        total_minutes = 0
        for i, result in enumerate(self.results):
            if i > 0:
                try:
                    current_time = datetime.fromisoformat(result['timestamp'])
                    prev_time = datetime.fromisoformat(self.results[i-1]['timestamp'])
                    diff = (current_time - prev_time).total_seconds() / 60
                    # Считаем только разумные интервалы (до 30 минут)
                    if diff <= 30:
                        total_minutes += diff
                except:
                    pass
        
        return int(total_minutes)
    
    def get_weak_topics(self, limit: int = 5) -> List[Dict]:
        """Получить темы с низкими баллами."""
        topic_scores = {}
        for result in self.results:
            topic_id = result['topic_id']
            if topic_id not in topic_scores:
                topic_scores[topic_id] = []
            topic_scores[topic_id].append(result['score'])
        
        # Средний балл по каждой теме
        weak_topics = []
        for topic_id, scores in topic_scores.items():
            avg_score = sum(scores) / len(scores)
            if avg_score < 2:
                weak_topics.append({
                    'topic_id': topic_id,
                    'average_score': avg_score,
                    'attempts': len(scores),
                    'last_score': scores[-1]
                })
        
        # Сортируем по среднему баллу
        weak_topics.sort(key=lambda x: x['average_score'])
        return weak_topics[:limit]
    
    def should_show_tip(self) -> Optional[str]:
        """Определить, нужно ли показать подсказку."""
        stats = self.get_stats()
        
        if stats['total_attempts'] == 0:
            return "💡 Совет: Начните с простых тем из блока 'Экономика'"
        
        if stats['average_score'] < 1.5:
            return "💡 Совет: Изучите раздел 'Полезные конструкции' в теории"
        
        if stats['streak'] >= 5:
            return "🔥 Отличная серия! Попробуйте более сложные темы"
        
        if stats['trend'] == 'down' and stats['total_attempts'] >= 5:
            return "📉 Результаты снижаются. Сделайте перерыв или изучите теорию"
        
        return None

class SmartRecommendations:
    """Умные рекомендации для пользователя."""
    
    @staticmethod
    def get_next_topic_recommendation(user_progress: UserProgress, topic_selector) -> Optional[Dict]:
        """Получить рекомендацию следующей темы."""
        stats = user_progress.get_stats()
        
        # Для новичков - простые темы
        if stats['total_attempts'] < 3:
            easy_blocks = ['Экономика', 'Социальные отношения']
            for block in easy_blocks:
                topic = topic_selector.get_random_from_block(
                    block, 
                    exclude_ids={r['topic_id'] for r in user_progress.results}
                )
                if topic:
                    return topic
        
        # Для опытных - работа над ошибками
        if stats['total_attempts'] >= 10:
            weak_topics = user_progress.get_weak_topics()
            if weak_topics:
                # Возвращаем тему, которую давно не повторяли
                oldest_weak = min(weak_topics, key=lambda x: x.get('last_attempt', 0))
                return topic_selector.topics_by_id.get(oldest_weak['topic_id'])
        
        # По умолчанию - рекомендации на основе истории
        return topic_selector.get_recommended_topics(user_progress.results, limit=1)[0] if topic_selector else None
