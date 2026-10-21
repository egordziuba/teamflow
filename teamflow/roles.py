"""Static role metadata and fail-closed validation; never launches a worker."""

CORE_ROLES = ('coordinator', 'analyst', 'implementer', 'verifier')
_PROJECT_TYPES = ('csv', 'website', 'desktop', 'automation', 'accounting',
                  'documents', 'career', 'research')
# Immutable backing records: title, scope, expected artifact, eligible projects.
_RECORDS = {
    'coordinator': ('Координатор', 'Определяет цель и необходимые роли.', 'Контракт задачи', _PROJECT_TYPES),
    'analyst': ('Аналитик', 'Проверяет предоставленный источник.', 'Анализ источника', _PROJECT_TYPES),
    'implementer': ('Исполнитель', 'Готовит результат по контракту.', 'Результат задачи', _PROJECT_TYPES),
    'verifier': ('Проверяющий', 'Независимо проверяет результат.', 'Отчёт проверки', _PROJECT_TYPES),
    'designer': ('Дизайнер', 'Предлагает композицию и визуальные правила.', 'Дизайн-спецификация, не готовый рендер', ('website', 'desktop', 'documents')),
    'copywriter': ('Редактор текстов', 'Готовит тексты по проверенным данным.', 'Тексты и структура сообщений', ('website', 'documents', 'career')),
    'researcher': ('Исследователь', 'Анализирует только предоставленные материалы.', 'Обзор с границами доказательств', ('website', 'automation', 'accounting', 'documents', 'career', 'research')),
    'data-specialist': ('Специалист по данным', 'Проектирует очистку и проверки данных.', 'Схема данных и правила качества', ('csv', 'automation', 'accounting', 'research')),
    'architect': ('Архитектор', 'Проектирует компоненты и границы ответственности.', 'Архитектура и контракты интерфейсов', ('website', 'desktop', 'automation')),
    'ui-tester': ('Специалист по UI-проверкам', 'Проектирует проверки интерфейса без исполнения.', 'План UI-тестов, не протокол выполненных тестов', ('website', 'desktop')),
    'seo-specialist': ('SEO-специалист', 'Анализирует предоставленную структуру сайта.', 'Рекомендации SEO и план проверки', ('website',)),
    'localization-editor': ('Редактор локализации', 'Адаптирует предоставленный текст под язык и аудиторию.', 'Локализованный текст и терминология', ('website', 'desktop', 'documents', 'career')),
    'document-specialist': ('Специалист по документам', 'Проектирует структуру и комплектность документов.', 'Структура документа и контрольный список', ('accounting', 'documents', 'career', 'research')),
}
ROLE_IDS = tuple(_RECORDS)


def allowed_specialists(project_type: str) -> list[str]:
    """Eligibility only: requesting no roles must still activate none."""
    if not isinstance(project_type, str) or project_type not in _PROJECT_TYPES:
        raise ValueError('unknown project_type')
    return [role for role, record in _RECORDS.items()
            if role not in CORE_ROLES and project_type in record[3]]


def validate_requests(project_type: str, requests: list[dict],
                      max_specialists: int = 3) -> list[dict]:
    """Return explicit requests; this function never activates workers."""
    allowed = allowed_specialists(project_type)
    seen = set()
    if type(max_specialists) is not int or not 0 <= max_specialists <= len(ROLE_IDS) - len(CORE_ROLES):
        raise ValueError('max_specialists must be an integer between 0 and 9 (not bool)')
    if not isinstance(requests, list):
        raise ValueError('requests must be a list')
    if len(requests) > max_specialists:
        raise ValueError('specialist request limit exceeded')
    for request in requests:
        if not isinstance(request, dict) or set(request) != {'role', 'reason', 'deliverable'}:
            raise ValueError('request must contain exactly role, reason, deliverable')
        if any(not isinstance(value, str) or not value.strip()
               for value in request.values()):
            raise ValueError('request values must be nonempty strings')
        role = request['role']
        if role not in allowed:
            raise ValueError('role is not an eligible specialist')
        if role in seen:
            raise ValueError('duplicate specialist role')
        seen.add(role)
    return [dict(request) for request in requests]


def catalog() -> dict:
    """Return detached metadata for core and optional roles (not activations)."""
    return {role: dict(title=title, description=description,
                       deliverable=deliverable, project_types=list(projects))
            for role, (title, description, deliverable, projects) in _RECORDS.items()}
