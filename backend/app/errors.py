class AnalysisUnavailable(Exception):
    """Исключение: сервис анализа временно недоступен или превышен тайм-аут."""
    pass


class InvalidAnalysisResult(Exception):
    """Исключение: результат анализа не соответствует контракту схемы."""
    pass
