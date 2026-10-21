class AnalysisUnavailable(Exception):
    """Сервис анализа (или LLM) временно недоступен."""


class InvalidAnalysisResult(Exception):
    """Результат анализа не прошел проверку контракта или самопроверку."""
