"""
Task runner usando threading — compatível com PythonAnywhere sem worker separado.
Cada tarefa roda em uma daemon thread dentro do processo web.
"""
import threading
import logging

logger = logging.getLogger(__name__)


def _run_in_thread(target, *args):
    """Executa `target(*args)` em uma daemon thread."""
    def wrapper():
        try:
            target(*args)
        except Exception:
            logger.exception('Background thread error in %s(%s)', target.__name__, args)

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()


def enqueue_flow_step(project_id: int):
    """Dispara o próximo passo do fluxo em background."""
    from apps.projects.services.flow_manager import run_next_step
    _run_in_thread(run_next_step, project_id)


def enqueue_persona_step(project_id: int, persona_key: str):
    """Dispara uma persona específica em background."""
    from apps.projects.services.flow_manager import run_persona_step
    _run_in_thread(run_persona_step, project_id, persona_key)


def enqueue_issue_creation(project_id: int):
    """Dispara a criação de Issues no GitHub em background."""
    from apps.projects.services.github_service import create_issues_from_project_task
    _run_in_thread(create_issues_from_project_task, project_id)
