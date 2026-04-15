"""
Calls the Anthropic API for each AI persona and persists the result as EmailMessage.
"""
import re
import logging
from decimal import Decimal

import anthropic
import markdown as md
import bleach

from apps.projects.models import Project, EmailMessage, PersonaState
from apps.controller.models import ControllerConfig

logger = logging.getLogger(__name__)

# Costs per million tokens (claude-sonnet-4 pricing, adjust as needed)
COST_PER_INPUT_TOKEN = Decimal('0.000003')    # $3 / 1M
COST_PER_OUTPUT_TOKEN = Decimal('0.000015')   # $15 / 1M

MODEL = 'claude-sonnet-4-20250514'

PERSONA_NAMES = {
    'po': 'Product Owner (PO)',
    'pm': 'Project Manager (PM)',
    'el': 'Engineering Lead (EL)',
    'dev1': 'Developer Frontend (DEV1)',
    'dev2': 'Developer Backend (DEV2)',
}

PERSONA_INITIALS = {
    'po': 'PO',
    'pm': 'PM',
    'el': 'EL',
    'dev1': 'D1',
    'dev2': 'D2',
}

SYSTEM_PROMPTS = {
    'po': """
Você é o Product Owner de uma empresa de software. Seu trabalho é:
- Representar os interesses do usuário/cliente acima de tudo.
- Refinar ideias vagas em requisitos claros e priorizados (formato MoSCoW).
- Mediar conflitos entre PM e EL quando afetam o valor entregue.
- Escrever emails profissionais, diretos, com bullet points quando necessário.
- Você DEFENDE escopo maior se isso agregar valor; resiste a cortes que prejudicam o usuário.
- Você só declara "APPROVED" quando os requisitos estão claros e consensuados.
- Você pode usar tabelas para comparar opções.
- Responda SEMPRE em português do Brasil.
Formato de email: assunto claro, destinatários explícitos, corpo estruturado.
""",
    'pm': """
Você é o Project Manager. Seu trabalho é:
- Transformar requisitos em um plano de execução com fases, dependências e riscos.
- Defender prazo e escopo controlado — você RESISTE a scope creep.
- Questionar o EL sobre complexidade técnica que possa atrasar entregas.
- Produzir tabelas de cronograma (Fase | Descrição | Estimativa | Risco).
- Você só declara "APPROVED" quando o plano está viável e os riscos mitigados.
- Responda SEMPRE em português do Brasil.
""",
    'el': """
Você é o Engineering Lead. Seu trabalho é:
- Avaliar viabilidade técnica e propor a arquitetura adequada.
- Defender qualidade: você rejeita soluções que criam dívida técnica excessiva.
- Questionar o PO sobre requisitos ambíguos que impactam implementação.
- Usar diagramas Mermaid quando útil para explicar arquitetura (coloque em bloco ```mermaid).
- Você só declara "APPROVED" quando a solução técnica está clara e sustentável.
- Responda SEMPRE em português do Brasil.
""",
    'dev1': """
Você é o Developer Frontend. Seu trabalho é:
- Detalhar a implementação de UI/UX: componentes, fluxo de navegação, estados de tela.
- Questionar sobre edge cases de interface.
- Quando solicitado, produzir o texto de uma GitHub Issue completa com: Título, Descrição,
  Critérios de Aceitação (checklist), Notas Técnicas, Labels sugeridos.
- Você só declara "APPROVED" quando a issue está detalhada o suficiente para implementação.
- Responda SEMPRE em português do Brasil.
""",
    'dev2': """
Você é o Developer Backend. Seu trabalho é:
- Detalhar a implementação de APIs, modelos de dados, lógica de negócio.
- Questionar sobre segurança, performance e integrações externas.
- Quando solicitado, produzir o texto de uma GitHub Issue completa com: Título, Descrição,
  Critérios de Aceitação (checklist), Notas Técnicas, Labels sugeridos.
- Você só declara "APPROVED" quando a issue está detalhada o suficiente para implementação.
- Responda SEMPRE em português do Brasil.
""",
}

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'pre', 'code', 'blockquote', 'table', 'thead', 'tbody',
    'tr', 'th', 'td', 'ul', 'ol', 'li', 'hr', 'img',
]
ALLOWED_ATTRS = {**bleach.sanitizer.ALLOWED_ATTRIBUTES, 'img': ['src', 'alt'], 'code': ['class']}


def render_markdown(text: str) -> str:
    html = md.markdown(
        text,
        extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists'],
    )
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


def calculate_cost(usage) -> Decimal:
    return (
        Decimal(usage.input_tokens) * COST_PER_INPUT_TOKEN
        + Decimal(usage.output_tokens) * COST_PER_OUTPUT_TOKEN
    )


def build_email_history_context(project: Project, max_emails: int = 20) -> str:
    emails = project.emails.order_by('-created_at')[:max_emails]
    emails = list(reversed(emails))
    lines = [f'## Histórico do Projeto: {project.title}', f'**Ideia original:** {project.original_idea}', '']
    for email in emails:
        lines.append(f'---')
        lines.append(f'**De:** {email.get_sender_display()}')
        lines.append(f'**Para:** {email.recipients_display}')
        lines.append(f'**Assunto:** {email.subject}')
        lines.append(email.body)
        lines.append('')
    return '\n'.join(lines)


def parse_persona_response(text: str) -> dict:
    """Parse the structured email response from a persona."""
    result = {
        'to': [],
        'cc': [],
        'subject': '',
        'body': text,
        'status': 'pending',
        'motivo_status': '',
    }

    lines = text.strip().split('\n')
    body_start = 0
    in_body = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith('PARA:') or upper.startswith('TO:'):
            raw = re.split(r'PARA:|TO:', stripped, flags=re.IGNORECASE, maxsplit=1)[-1].strip()
            result['to'] = [r.strip().lower() for r in re.split(r'[,;]', raw) if r.strip()]
        elif upper.startswith('CC:'):
            raw = stripped[3:].strip()
            result['cc'] = [r.strip().lower() for r in re.split(r'[,;]', raw) if r.strip()]
        elif upper.startswith('ASSUNTO:') or upper.startswith('SUBJECT:'):
            result['subject'] = re.split(r'ASSUNTO:|SUBJECT:', stripped, flags=re.IGNORECASE, maxsplit=1)[-1].strip()
        elif upper.startswith('CORPO:') or upper.startswith('BODY:'):
            body_start = i + 1
            in_body = True
        elif upper.startswith('STATUS:') and not in_body:
            raw = re.split(r'STATUS:', stripped, flags=re.IGNORECASE, maxsplit=1)[-1].strip().upper()
            if 'APPROVED' in raw:
                result['status'] = 'approved'
            elif 'BLOCKED' in raw:
                result['status'] = 'blocked'
            else:
                result['status'] = 'pending'
        elif (upper.startswith('MOTIVO_STATUS:') or upper.startswith('REASON:')) and not in_body:
            result['motivo_status'] = re.split(r'MOTIVO_STATUS:|REASON:', stripped, flags=re.IGNORECASE, maxsplit=1)[-1].strip()

    if body_start > 0:
        # Find end of body (STATUS line after body)
        body_lines = []
        for line in lines[body_start:]:
            upper_line = line.strip().upper()
            if upper_line.startswith('STATUS:') or upper_line.startswith('MOTIVO_STATUS:'):
                # Parse status from here
                if upper_line.startswith('STATUS:'):
                    raw = re.split(r'STATUS:', line.strip(), flags=re.IGNORECASE, maxsplit=1)[-1].strip().upper()
                    if 'APPROVED' in raw:
                        result['status'] = 'approved'
                    elif 'BLOCKED' in raw:
                        result['status'] = 'blocked'
                    else:
                        result['status'] = 'pending'
                elif upper_line.startswith('MOTIVO_STATUS:'):
                    result['motivo_status'] = re.split(r'MOTIVO_STATUS:', line.strip(), flags=re.IGNORECASE, maxsplit=1)[-1].strip()
            else:
                body_lines.append(line)
        result['body'] = '\n'.join(body_lines).strip()

    # Normalize recipient keys to known persona codes
    valid_personas = {'po', 'pm', 'el', 'dev1', 'dev2', 'user', 'todos', 'all'}
    persona_aliases = {
        'product owner': 'po', 'productowner': 'po',
        'project manager': 'pm', 'projectmanager': 'pm',
        'engineering lead': 'el', 'engineeringlead': 'el',
        'developer frontend': 'dev1', 'developerfrontend': 'dev1', 'frontend': 'dev1',
        'developer backend': 'dev2', 'developerbackend': 'dev2', 'backend': 'dev2',
        'dev 1': 'dev1', 'dev 2': 'dev2',
        'all': 'todos', 'todos': 'todos',
    }

    def normalize(keys):
        result = []
        for k in keys:
            k_lower = k.lower().strip()
            if k_lower in valid_personas:
                result.append(k_lower)
            elif k_lower in persona_aliases:
                result.append(persona_aliases[k_lower])
            elif k_lower:
                result.append(k_lower)
        if 'todos' in result or 'all' in result:
            return ['po', 'pm', 'el', 'dev1', 'dev2']
        return result

    result['to'] = normalize(result['to'])
    result['cc'] = normalize(result['cc'])

    if not result['subject']:
        result['subject'] = 'Sem assunto'

    return result


def call_persona(
    persona_key: str,
    project: Project,
    trigger_email: EmailMessage | None = None,
    config: ControllerConfig = None,
) -> EmailMessage:
    """Call Anthropic API for a persona and persist the resulting EmailMessage."""
    if config is None:
        config = ControllerConfig.get_for_user(project.owner)

    api_key = config.anthropic_api_key or __import__('django.conf', fromlist=['settings']).settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError('Chave da API Anthropic não configurada. Acesse o Controller para configurar.')

    client = anthropic.Anthropic(api_key=api_key)

    history = build_email_history_context(project)

    if trigger_email:
        trigger_block = f"""O email abaixo acabou de chegar para você:

{format_email(trigger_email)}"""
    else:
        trigger_block = 'Inicie o próximo passo conforme seu papel no projeto.'

    user_message = f"""{history}

---
INSTRUÇÃO: Você é {PERSONA_NAMES[persona_key]}.
{trigger_block}

Escreva seu próximo email. Use EXATAMENTE este formato:
PARA: [personas separadas por vírgula — use: po, pm, el, dev1, dev2]
CC: [opcional]
ASSUNTO: [assunto claro]
CORPO:
[conteúdo do email em Markdown]

STATUS: [PENDING | APPROVED | BLOCKED]
MOTIVO_STATUS: [breve justificativa do seu status atual]
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPTS[persona_key],
            messages=[{'role': 'user', 'content': user_message}],
        )
    except anthropic.APIError as e:
        logger.error('Anthropic API error for persona %s: %s', persona_key, e)
        raise

    raw_text = response.content[0].text
    parsed = parse_persona_response(raw_text)

    cost = calculate_cost(response.usage)
    tokens = response.usage.input_tokens + response.usage.output_tokens

    email = EmailMessage.objects.create(
        project=project,
        sender=persona_key,
        recipients=parsed['to'],
        cc=parsed.get('cc', []),
        subject=parsed['subject'],
        body=parsed['body'],
        body_html=render_markdown(parsed['body']),
        in_reply_to=trigger_email,
        tokens_used=tokens,
        cost_usd=cost,
    )

    PersonaState.objects.update_or_create(
        project=project,
        persona=persona_key,
        defaults={
            'status': parsed['status'],
            'last_concern': parsed.get('motivo_status', ''),
        },
    )

    project.total_tokens_used += tokens
    project.total_cost_usd += cost
    project.save(update_fields=['total_tokens_used', 'total_cost_usd', 'updated_at'])

    return email


def format_email(email: EmailMessage) -> str:
    return (
        f'De: {email.get_sender_display()}\n'
        f'Para: {email.recipients_display}\n'
        f'Assunto: {email.subject}\n\n'
        f'{email.body}'
    )
