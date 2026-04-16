"""
Orchestrates the AI discussion loop.
Flow: PO Brief → FC (field research) → EL (technical) → consensus → DEV1+DEV2 generate specs
Delta mode: if specs already exist, DEV1+DEV2 generate delta specs only.
"""
import logging

from apps.projects.models import Project, EmailMessage, PersonaState
from apps.controller.models import ControllerConfig
from apps.controller.budget_guard import check_budget
from .persona_engine import call_persona, SYSTEM_PROMPTS

logger = logging.getLogger(__name__)

FLOW_PERSONAS = ['po', 'fc', 'el', 'dev1', 'dev2']
CORE_PERSONAS = ['po', 'fc', 'el']


def next_steps(project: Project) -> list[str]:
    """
    Returns list of persona keys that should respond next.

    Rules (in order):
    1. No AI emails yet → PO creates Brief
    2. PO spoke, FC hasn't → FC does field research
    3. FC spoke, EL hasn't → EL does technical evaluation
    4. Anyone BLOCKED → PO resolves (unless PO is blocked → EL resolves)
    5. All CORE_PERSONAS APPROVED → DEV1 + DEV2 generate specs
    6. All FLOW_PERSONAS APPROVED → consensus reached
    7. Default: whoever hasn't responded to the latest thread
    """
    ai_emails = project.emails.filter(sender__in=FLOW_PERSONAS).order_by('created_at')
    states = {s.persona: s.status for s in project.states.all()}
    senders = set(ai_emails.values_list('sender', flat=True))

    if not ai_emails.exists():
        return ['po']

    if 'po' in senders and 'fc' not in senders:
        return ['fc']

    if 'fc' in senders and 'el' not in senders:
        return ['el']

    blocked = [p for p, s in states.items() if s == 'blocked']
    if blocked:
        return ['po'] if 'po' not in blocked else ['el']

    core_approved = all(states.get(p) == 'approved' for p in CORE_PERSONAS)
    if core_approved:
        missing_devs = [d for d in ['dev1', 'dev2'] if d not in senders]
        if missing_devs:
            return missing_devs
        if all(states.get(p) == 'approved' for p in FLOW_PERSONAS):
            return []  # Consensus

    # Default: last sender determines who responds
    last_sender = ai_emails.last().sender if ai_emails.exists() else None
    if last_sender in ('fc', 'el') and states.get('po') != 'approved':
        return ['po']
    if last_sender == 'po':
        if states.get('fc') != 'approved':
            return ['fc']
        if states.get('el') != 'approved':
            return ['el']

    return []


def is_consensus_reached(project: Project) -> bool:
    states = {s.persona: s.status for s in project.states.all()}
    return all(states.get(p) == 'approved' for p in FLOW_PERSONAS)


def is_delta_run(project: Project) -> bool:
    """True if specs already exist — this is a refinement cycle."""
    return project.specs.exists()


def run_next_step(project_id: int) -> None:
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        logger.error('Project %d not found', project_id)
        return

    if project.status in ('completed', 'paused'):
        return

    config = ControllerConfig.get_for_user(project.owner)

    budget = check_budget(project, config)
    if not budget['ok']:
        _pause_project(project, budget['reason'])
        return

    personas = next_steps(project)
    if not personas:
        if is_consensus_reached(project):
            _handle_consensus(project, config)
        return

    last_email = project.emails.filter(sender__in=FLOW_PERSONAS).last() or project.emails.last()
    delta = is_delta_run(project)

    for persona_key in personas:
        budget = check_budget(project, config)
        if not budget['ok']:
            _pause_project(project, budget['reason'])
            return

        # Extra instruction for DEV personas: full spec vs delta
        extra = ''
        if persona_key in ('dev1', 'dev2') and delta:
            extra = (
                '\n\n⚠️ MODO DELTA ATIVO: Já existem especificações para este projeto. '
                'Gere APENAS as specs do que foi ADICIONADO, MODIFICADO ou REMOVIDO em relação à versão anterior. '
                'Marque cada item com 🟢 ADICIONADO, 🟡 MODIFICADO ou 🔴 REMOVIDO.'
            )
        elif persona_key in ('dev1', 'dev2'):
            extra = '\n\nGere as especificações completas conforme seu papel (UI+Business para DEV1, Backend+Técnica para DEV2).'

        try:
            email = call_persona(
                persona_key=persona_key,
                project=project,
                trigger_email=last_email,
                config=config,
                extra_instruction=extra,
            )
            last_email = email
        except Exception as e:
            logger.exception('Error calling persona %s for project %d: %s', persona_key, project_id, e)
            _error_message(project, persona_key, str(e))
            return

    project.refresh_from_db()
    if is_consensus_reached(project):
        _handle_consensus(project, config)
        return

    from apps.projects.tasks import enqueue_flow_step
    enqueue_flow_step(project.id)


def _handle_consensus(project: Project, config: ControllerConfig) -> None:
    from apps.projects.services.spec_service import extract_and_save_specs

    # Extract specs from dev emails
    version_type = 'delta' if is_delta_run(project) else 'full'
    version_num = project.specs.values('version').distinct().count() + 1
    extract_and_save_specs(project, version_type=version_type, version=version_num)

    label = 'Especificações delta geradas' if version_type == 'delta' else 'Especificações completas geradas'
    body = (
        f'**{label}!** Todas as personas aprovaram.\n\n'
        'As especificações foram salvas e estão disponíveis abaixo. '
        'Envie feedback para gerar um novo ciclo com specs delta.'
    )
    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject=label,
        body=body,
        body_html=f'<p><strong>{label}!</strong> Todas as personas aprovaram.</p>'
                  '<p>As especificações foram salvas abaixo. '
                  'Envie feedback para gerar um novo ciclo com specs delta.</p>',
        is_read=False,
    )
    project.status = 'dormant'
    project.save(update_fields=['status', 'updated_at'])


def _pause_project(project: Project, reason: str) -> None:
    from apps.projects.services.persona_engine import render_markdown
    body = f'O fluxo foi interrompido automaticamente.\n\n**Motivo:** {reason}'
    EmailMessage.objects.create(
        project=project, sender='system', recipients=[],
        subject='Fluxo pausado pelo Controller',
        body=body, body_html=render_markdown(body), is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at'])


def _error_message(project: Project, persona_key: str, error: str) -> None:
    from apps.projects.services.persona_engine import PERSONA_NAMES, render_markdown
    body = f'Erro ao processar resposta de {PERSONA_NAMES.get(persona_key, persona_key)}.\n\n`{error}`'
    EmailMessage.objects.create(
        project=project, sender='system', recipients=[],
        subject=f'Erro — {PERSONA_NAMES.get(persona_key, persona_key)}',
        body=body, body_html=render_markdown(body), is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at'])
