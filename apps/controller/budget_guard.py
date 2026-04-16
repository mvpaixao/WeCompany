from apps.projects.models import Project
from apps.controller.models import ControllerConfig
from apps.projects.services.persona_engine import SYSTEM_PROMPTS


def check_budget(project: Project, config: ControllerConfig) -> dict:
    """
    Called by flow_manager before each step.
    Returns {'ok': True} or {'ok': False, 'reason': str}
    If project.unlimited_tokens is True, skips token and cost checks.
    """
    if not project.unlimited_tokens:
        if project.total_tokens_used >= config.max_tokens_per_project:
            return {
                'ok': False,
                'reason': f'Limite de tokens atingido ({config.max_tokens_per_project:,} tokens)',
            }

        if float(project.total_cost_usd) >= float(config.max_cost_usd_per_project):
            return {
                'ok': False,
                'reason': f'Limite de custo atingido (${config.max_cost_usd_per_project})',
            }

    ai_rounds = project.emails.filter(sender__in=list(SYSTEM_PROMPTS.keys())).count()
    if ai_rounds >= config.max_rounds_per_flow:
        return {
            'ok': False,
            'reason': f'Número máximo de rodadas atingido ({config.max_rounds_per_flow})',
        }

    return {'ok': True}
