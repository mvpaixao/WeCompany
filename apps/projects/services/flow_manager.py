"""
Orchestrates the AI discussion loop.
Determines which persona speaks next, calls them, and checks for consensus.
"""
import logging

from apps.projects.models import Project, EmailMessage, PersonaState
from apps.controller.models import ControllerConfig
from apps.controller.budget_guard import check_budget
from .persona_engine import call_persona

logger = logging.getLogger(__name__)

# Personas that participate in the main flow
FLOW_PERSONAS = ['po', 'pm', 'el', 'dev1', 'dev2']
CORE_PERSONAS = ['po', 'pm', 'el']  # Must approve before DEV phase


def next_steps(project: Project) -> list[str]:
    """
    Returns list of persona keys that should respond next.
    Rules (checked in order):
    1. New project → PO creates Brief
    2. After Brief → PM then EL
    3. If anyone BLOCKED → PO responds to unblock
    4. If all CORE_PERSONAS APPROVED → DEV1 and DEV2 generate Issues
    5. If DEVs also APPROVED → consensus reached
    """
    ai_emails = project.emails.filter(sender__in=FLOW_PERSONAS).order_by('created_at')
    states = {s.persona: s.status for s in project.states.all()}

    # Rule 1: No AI emails yet → PO goes first
    if not ai_emails.exists():
        return ['po']

    senders_so_far = set(ai_emails.values_list('sender', flat=True))

    # Rule 2: PO has spoken but PM hasn't
    if 'po' in senders_so_far and 'pm' not in senders_so_far:
        return ['pm']

    # PM has spoken but EL hasn't
    if 'pm' in senders_so_far and 'el' not in senders_so_far:
        return ['el']

    # Rule 3: Anyone is BLOCKED → PO must respond
    blocked = [p for p, s in states.items() if s == 'blocked']
    if blocked:
        # Only have PO respond if PO isn't the one blocked
        if 'po' not in blocked:
            return ['po']
        # If PO is blocked, EL responds
        return ['el']

    # Rule 4: All core personas approved → DEV phase
    core_approved = all(states.get(p) == 'approved' for p in CORE_PERSONAS)
    if core_approved:
        devs_done = 'dev1' in senders_so_far and 'dev2' in senders_so_far
        if not devs_done:
            missing_devs = []
            if 'dev1' not in senders_so_far:
                missing_devs.append('dev1')
            if 'dev2' not in senders_so_far:
                missing_devs.append('dev2')
            return missing_devs or []

        # Rule 5: All personas approved → consensus
        all_approved = all(states.get(p) == 'approved' for p in FLOW_PERSONAS)
        if all_approved:
            return []  # Done

    # Default: determine who hasn't responded to the last few emails
    last_sender = ai_emails.last().sender if ai_emails.exists() else None
    if last_sender == 'po':
        if states.get('pm') != 'approved':
            return ['pm']
        if states.get('el') != 'approved':
            return ['el']
    elif last_sender in ('pm', 'el'):
        if states.get('po') not in ('approved',):
            return ['po']

    return []


def is_consensus_reached(project: Project) -> bool:
    states = {s.persona: s.status for s in project.states.all()}
    return all(states.get(p) == 'approved' for p in FLOW_PERSONAS)


def run_next_step(project_id: int) -> None:
    """
    Main entry point called by Django Q worker.
    Determines next step, calls personas, checks consensus.
    """
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        logger.error('Project %d not found', project_id)
        return

    if project.status in ('completed', 'paused'):
        logger.info('Project %d is %s, skipping step', project_id, project.status)
        return

    config = ControllerConfig.get_for_user(project.owner)

    # Budget check
    budget = check_budget(project, config)
    if not budget['ok']:
        _pause_project(project, budget['reason'])
        return

    personas = next_steps(project)
    if not personas:
        # Check if consensus is reached
        if is_consensus_reached(project):
            _handle_consensus(project, config)
        else:
            logger.info('Project %d: no next steps determined, flow stalled', project_id)
        return

    last_email = project.emails.filter(sender__in=FLOW_PERSONAS).last() or project.emails.last()

    for persona_key in personas:
        budget = check_budget(project, config)
        if not budget['ok']:
            _pause_project(project, budget['reason'])
            return

        try:
            email = call_persona(
                persona_key=persona_key,
                project=project,
                trigger_email=last_email,
                config=config,
            )
            last_email = email
            logger.info('Project %d: %s responded', project_id, persona_key)
        except Exception as e:
            logger.exception('Error calling persona %s for project %d: %s', persona_key, project_id, e)
            _error_message(project, persona_key, str(e))
            return

    # Reload project to check fresh state
    project.refresh_from_db()

    # Check consensus after this round
    if is_consensus_reached(project):
        _handle_consensus(project, config)
        return

    # Continue loop: schedule next step
    from apps.projects.tasks import enqueue_flow_step
    enqueue_flow_step(project.id)


def _handle_consensus(project: Project, config: ControllerConfig) -> None:
    """All personas approved — mark dormant and optionally create issues."""
    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject='Consenso atingido!',
        body=(
            'Todas as personas aprovaram. O projeto está pronto para geração de GitHub Issues.\n\n'
            'Use o botão **"Criar Issues no GitHub"** para publicar as issues, '
            'ou envie feedback para refinar mais.'
        ),
        body_html=(
            '<p><strong>Todas as personas aprovaram.</strong> O projeto está pronto para geração de GitHub Issues.</p>'
            '<p>Use o botão <strong>"Criar Issues no GitHub"</strong> para publicar as issues, '
            'ou envie feedback para refinar mais.</p>'
        ),
        is_read=False,
    )
    project.status = 'dormant'
    project.save(update_fields=['status', 'updated_at'])

    if config.auto_create_github_issues and (config.github_token and (project.github_repo or config.github_default_repo)):
        from apps.projects.tasks import enqueue_issue_creation
        enqueue_issue_creation(project.id)


def _pause_project(project: Project, reason: str) -> None:
    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject='Fluxo pausado pelo Controller',
        body=f'O fluxo foi interrompido automaticamente.\n\n**Motivo:** {reason}',
        body_html=f'<p>O fluxo foi interrompido automaticamente.</p><p><strong>Motivo:</strong> {reason}</p>',
        is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at'])
    logger.warning('Project %d paused: %s', project.id, reason)


def _error_message(project: Project, persona_key: str, error: str) -> None:
    from apps.projects.services.persona_engine import PERSONA_NAMES
    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject=f'Erro ao chamar {PERSONA_NAMES.get(persona_key, persona_key)}',
        body=f'Ocorreu um erro ao processar a resposta desta persona.\n\n`{error}`',
        body_html=f'<p>Ocorreu um erro ao processar a resposta desta persona.</p><pre>{error}</pre>',
        is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at'])
