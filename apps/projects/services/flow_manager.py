"""
Orchestrates the AI discussion loop.
Flow: PO Brief → FC (field research) → EL (technical) → consensus → DEV1+DEV2 generate specs
Delta mode: if specs already exist, DEV1+DEV2 generate delta specs only.
"""
import logging

from apps.projects.models import Project, EmailMessage, PersonaState
from apps.controller.models import ControllerConfig
from apps.controller.budget_guard import check_budget
from .persona_engine import call_persona, SYSTEM_PROMPTS, PERSONA_NAMES

logger = logging.getLogger(__name__)

FLOW_PERSONAS = ['po', 'fc', 'el', 'dev1', 'dev2']
CORE_PERSONAS = ['po', 'fc', 'el']


def _set_activity(project: Project, msg: str) -> None:
    """Updates the visible activity status for the user and logs it."""
    logger.info('[Project %d] %s', project.id, msg)
    Project.objects.filter(pk=project.pk).update(current_activity=msg)
    project.current_activity = msg


def next_steps(project: Project) -> list[str]:
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
            return []

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
    return project.specs.exists()


def run_next_step(project_id: int) -> None:
    logger.info('=== [Project %d] Iniciando próximo passo ===', project_id)

    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        logger.error('[Project %d] Projeto não encontrado', project_id)
        return

    if project.status in ('completed', 'paused'):
        logger.info('[Project %d] Status=%s, abortando', project_id, project.status)
        return

    config = ControllerConfig.get_for_user(project.owner)

    budget = check_budget(project, config)
    if not budget['ok']:
        logger.warning('[Project %d] Budget excedido: %s', project_id, budget['reason'])
        _set_activity(project, f'Pausado: {budget["reason"]}')
        _pause_project(project, budget['reason'])
        return

    personas = next_steps(project)
    logger.info('[Project %d] Próximas personas: %s', project_id, personas or 'nenhuma')

    if not personas:
        if is_consensus_reached(project):
            logger.info('[Project %d] Consenso atingido — gerando specs', project_id)
            _set_activity(project, 'Consenso atingido — extraindo especificações...')
            _handle_consensus(project, config)
        else:
            logger.warning('[Project %d] Sem próximas personas e sem consenso — fluxo parado', project_id)
            _set_activity(project, '')
        return

    last_email = project.emails.filter(sender__in=FLOW_PERSONAS).last() or project.emails.last()
    delta = is_delta_run(project)

    for persona_key in personas:
        # Check if project was suspended while we were processing
        project.refresh_from_db()
        if project.status in ('paused', 'completed'):
            logger.info('[Project %d] Projeto %s durante loop — abortando', project_id, project.status)
            return

        budget = check_budget(project, config)
        if not budget['ok']:
            logger.warning('[Project %d] Budget excedido antes de %s', project_id, persona_key)
            _set_activity(project, f'Pausado: {budget["reason"]}')
            _pause_project(project, budget['reason'])
            return

        name = PERSONA_NAMES.get(persona_key, persona_key)
        _set_activity(project, f'Enviando requisição para {name}...')
        logger.info('[Project %d] → Chamando %s (delta=%s)', project_id, name, delta)

        extra = ''
        if persona_key in ('dev1', 'dev2') and delta:
            extra = (
                '\n\n⚠️ MODO DELTA ATIVO: Já existem especificações para este projeto. '
                'Gere APENAS as specs do que foi ADICIONADO, MODIFICADO ou REMOVIDO. '
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
            status = project.states.filter(persona=persona_key).values_list('status', flat=True).first()
            logger.info(
                '[Project %d] ← %s respondeu | status=%s | tokens=%d | custo=$%.5f',
                project_id, name, status, email.tokens_used, float(email.cost_usd),
            )
            _set_activity(project, f'{name} respondeu ({status}) — total: {project.total_tokens_used:,} tokens')

        except Exception as e:
            logger.exception('[Project %d] ERRO ao chamar %s: %s', project_id, name, e)
            _set_activity(project, f'Erro ao chamar {name}: {e}')
            _error_message(project, persona_key, str(e))
            return

    project.refresh_from_db()

    if is_consensus_reached(project):
        logger.info('[Project %d] Consenso atingido após rodada', project_id)
        _set_activity(project, 'Consenso atingido — extraindo especificações...')
        _handle_consensus(project, config)
        return

    # Pause here — user must click "Seguir" to trigger the next round
    _set_activity(project, '')
    logger.info('[Project %d] Aguardando ação do usuário para continuar', project_id)


def _handle_consensus(project: Project, config: ControllerConfig) -> None:
    from apps.projects.services.spec_service import extract_and_save_specs

    version_type = 'delta' if is_delta_run(project) else 'full'
    version_num = project.specs.values('version').distinct().count() + 1
    logger.info('[Project %d] Extraindo specs versão %d (%s)', project.id, version_num, version_type)

    extract_and_save_specs(project, version_type=version_type, version=version_num)

    label = 'Especificações delta geradas' if version_type == 'delta' else 'Especificações completas geradas'
    logger.info('[Project %d] %s', project.id, label)

    body = (
        f'**{label}!** Todas as personas aprovaram.\n\n'
        'As especificações foram salvas e estão disponíveis abaixo. '
        'Envie feedback para gerar um novo ciclo com specs delta.'
    )
    EmailMessage.objects.create(
        project=project, sender='system', recipients=[],
        subject=label, body=body,
        body_html=f'<p><strong>{label}!</strong> Todas as personas aprovaram.</p>'
                  '<p>Envie feedback para gerar um novo ciclo com specs delta.</p>',
        is_read=False,
    )
    project.status = 'dormant'
    _set_activity(project, '')
    project.save(update_fields=['status', 'updated_at', 'current_activity'])


def _pause_project(project: Project, reason: str) -> None:
    from apps.projects.services.persona_engine import render_markdown
    logger.warning('[Project %d] Pausado: %s', project.id, reason)
    body = f'O fluxo foi interrompido automaticamente.\n\n**Motivo:** {reason}'
    EmailMessage.objects.create(
        project=project, sender='system', recipients=[],
        subject='Fluxo pausado pelo Controller',
        body=body, body_html=render_markdown(body), is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at', 'current_activity'])


def _error_message(project: Project, persona_key: str, error: str) -> None:
    from apps.projects.services.persona_engine import render_markdown
    name = PERSONA_NAMES.get(persona_key, persona_key)
    body = f'Erro ao processar resposta de {name}.\n\n`{error}`'
    EmailMessage.objects.create(
        project=project, sender='system', recipients=[],
        subject=f'Erro — {name}',
        body=body, body_html=render_markdown(body), is_read=False,
    )
    project.status = 'paused'
    project.save(update_fields=['status', 'updated_at', 'current_activity'])
