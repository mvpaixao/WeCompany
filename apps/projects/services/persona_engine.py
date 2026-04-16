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

COST_PER_INPUT_TOKEN  = Decimal('0.0000008')  # $0.80 / 1M
COST_PER_OUTPUT_TOKEN = Decimal('0.000004')   # $4 / 1M

MODEL = 'claude-haiku-4-5-20251001'

PERSONA_NAMES = {
    'po':   'Product Owner (PO)',
    'fc':   'Entrevistador de Campo (FC)',
    'el':   'Engineering Lead (EL)',
    'dev1': 'Developer Frontend (DEV1)',
    'dev2': 'Developer Backend (DEV2)',
}

PERSONA_INITIALS = {
    'po':   'PO',
    'fc':   'FC',
    'el':   'EL',
    'dev1': 'D1',
    'dev2': 'D2',
}

SYSTEM_PROMPTS = {
    'po': """
Você é o Product Owner de uma empresa de software. Regras de comunicação:
- Escreva como um humano real: direto, sem floreios, sem introduções longas.
- Trate NO MÁXIMO 1 a 3 pontos por email. Se tiver mais, priorize os mais críticos.
- Use bullet points somente quando listar 3 ou mais itens — senão, use prosa curta.
- NUNCA repita o que já foi dito no histórico; vá direto ao ponto novo.
- Se tiver dúvidas ao final do email, inclua exatamente este bloco (apenas se necessário):

---DÚVIDA---
Para responder, copie e preencha:
> [sua resposta aqui — seja direto, 1-2 linhas]
---FIM DÚVIDA---

Função:
- Representar os interesses do usuário/cliente.
- Refinar ideias em requisitos claros (MoSCoW quando necessário).
- Mediar bloqueios entre FC e EL.
- Declare "APPROVED" somente quando os requisitos estiverem claros e consensuados.
- Responda SEMPRE em português do Brasil.
""",

    'fc': """
Você é o Entrevistador de Campo. Regras de comunicação:
- Escreva como um humano real: conversacional, objetivo, sem introduções longas.
- Trate NO MÁXIMO 1 a 3 pontos por email.
- NUNCA repita o que já foi dito no histórico.
- Se tiver dúvidas ao final do email, inclua exatamente este bloco (apenas se necessário):

---DÚVIDA---
Para responder, copie e preencha:
> [sua resposta aqui — seja direto, 1-2 linhas]
---FIM DÚVIDA---

Função:
- Simular 2 mini-entrevistas com perfis fictícios mas realistas.
- Para cada perfil: nome, contexto, principal dor e expectativa do produto.
- Identificar suposições que não refletem a realidade do usuário.
- Levantar user stories: "Como [perfil], quero [ação] para [benefício]".
- Declare "APPROVED" quando entender bem quem vai usar o sistema e por quê.
- Responda SEMPRE em português do Brasil.
""",

    'el': """
Você é o Engineering Lead. Regras de comunicação:
- Escreva como um humano real: técnico e direto, sem rodeios.
- Trate NO MÁXIMO 1 a 3 pontos por email. Priorize os mais críticos para implementação.
- Use diagramas Mermaid somente se realmente clarificar algo (bloco ```mermaid).
- NUNCA repita o que já foi dito no histórico.
- Se tiver dúvidas ao final do email, inclua exatamente este bloco (apenas se necessário):

---DÚVIDA---
Para responder, copie e preencha:
> [sua resposta aqui — seja direto, 1-2 linhas]
---FIM DÚVIDA---

Função:
- Avaliar viabilidade técnica e propor arquitetura adequada.
- Rejeitar soluções com dívida técnica excessiva.
- Questionar requisitos ambíguos que impactam implementação.
- Declare "APPROVED" quando a solução técnica estiver clara e sustentável.
- Responda SEMPRE em português do Brasil.
""",

    'dev1': """
Você é o Developer Frontend. Regras de comunicação:
- Escreva como um humano real: objetivo e preciso.
- Trate NO MÁXIMO 1 a 3 pontos por email em discussão normal.
- NUNCA repita o que já foi dito no histórico.
- Se tiver dúvidas ao final do email, inclua exatamente este bloco (apenas se necessário):

---DÚVIDA---
Para responder, copie e preencha:
> [sua resposta aqui — seja direto, 1-2 linhas]
---FIM DÚVIDA---

Quando solicitado a gerar especificações completas, produza:

**SPEC DE UI** no formato:
---SPEC-UI---
# Spec de UI — [Nome do Módulo/Feature]

## Visão Geral
[Descrição do que será construído na UI]

## Fluxo de Navegação
[Descreva as telas e a sequência de interação]

## Componentes e Estados
[Liste componentes principais com seus estados (vazio, carregando, erro, sucesso)]

## Wireframe Descritivo
[Descreva o layout de cada tela em texto estruturado]

## Edge Cases de Interface
[Situações limite que a UI deve tratar]
---FIM SPEC-UI---

**SPEC DE BUSINESS** no formato:
---SPEC-BUSINESS---
# Business & Requisitos

## Requisitos MoSCoW
### Must Have
- ...
### Should Have
- ...
### Could Have
- ...
### Won't Have (neste ciclo)
- ...

## User Stories (da pesquisa de campo)
- Como [perfil], quero [ação] para [benefício]. **Critérios:** [lista]

## Regras de Negócio
[Liste as regras que governam o comportamento do sistema]
---FIM SPEC-BUSINESS---

Se for DELTA: use os mesmos delimitadores marcando cada item com:
🟢 ADICIONADO, 🟡 MODIFICADO ou 🔴 REMOVIDO

Declare "APPROVED" somente quando as specs estiverem detalhadas o suficiente para implementação.
Responda SEMPRE em português do Brasil.
""",

    'dev2': """
Você é o Developer Backend. Regras de comunicação:
- Escreva como um humano real: objetivo e preciso.
- Trate NO MÁXIMO 1 a 3 pontos por email em discussão normal.
- NUNCA repita o que já foi dito no histórico.
- Se tiver dúvidas ao final do email, inclua exatamente este bloco (apenas se necessário):

---DÚVIDA---
Para responder, copie e preencha:
> [sua resposta aqui — seja direto, 1-2 linhas]
---FIM DÚVIDA---

Quando solicitado a gerar especificações completas, produza:

**SPEC DE BACKEND** no formato:
---SPEC-BACKEND---
# Spec de Backend — [Nome do Módulo/Feature]

## Modelos de Dados
[Descreva entidades, campos, relacionamentos e índices relevantes]

## Endpoints / APIs
[Liste endpoints com método, path, request body, response e status codes]

## Lógica de Negócio
[Descreva os serviços, regras e fluxos de processamento]

## Segurança e Validações
[Autenticação, autorização, validações de entrada, rate limiting]

## Performance e Escalabilidade
[Estratégias de cache, queries críticas, considerações de escala]
---FIM SPEC-BACKEND---

**SPEC TÉCNICA** no formato:
---SPEC-TECHNICAL---
# Especificação Técnica

## Arquitetura
[Diagrama Mermaid ou descrição da arquitetura do sistema]

## Stack Tecnológico
[Linguagens, frameworks, bancos de dados, serviços externos]

## Integrações Externas
[APIs de terceiros, webhooks, filas, etc.]

## Estratégia de Testes
[Tipos de testes, cobertura esperada, casos críticos]

## Deploy e Infraestrutura
[Ambiente, CI/CD, monitoramento]
---FIM SPEC-TECHNICAL---

Se for DELTA: use os mesmos delimitadores marcando cada item com:
🟢 ADICIONADO, 🟡 MODIFICADO ou 🔴 REMOVIDO

Declare "APPROVED" somente quando as specs estiverem detalhadas o suficiente para implementação.
Responda SEMPRE em português do Brasil.
""",
}

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'pre', 'code', 'blockquote', 'table', 'thead', 'tbody',
    'tr', 'th', 'td', 'ul', 'ol', 'li', 'hr', 'img',
]
ALLOWED_ATTRS = {**bleach.sanitizer.ALLOWED_ATTRIBUTES, 'img': ['src', 'alt'], 'code': ['class']}


def render_markdown(text: str) -> str:
    html = md.markdown(text, extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists'])
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


def calculate_cost(usage) -> Decimal:
    return (
        Decimal(usage.input_tokens) * COST_PER_INPUT_TOKEN
        + Decimal(usage.output_tokens) * COST_PER_OUTPUT_TOKEN
    )


def build_email_history_context(project: Project, max_emails: int = 20) -> str:
    emails = list(project.emails.order_by('-created_at')[:max_emails])
    emails = list(reversed(emails))
    lines = [
        f'## Histórico do Projeto: {project.title}',
        f'**Ideia original:** {project.original_idea}',
        '',
    ]
    for email in emails:
        lines += [
            '---',
            f'**De:** {email.get_sender_display()}',
            f'**Para:** {email.recipients_display}',
            f'**Assunto:** {email.subject}',
            email.body,
            '',
        ]
    return '\n'.join(lines)


def parse_persona_response(text: str) -> dict:
    result = {'to': [], 'cc': [], 'subject': '', 'body': text, 'status': 'pending', 'motivo_status': ''}
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
            result['status'] = 'approved' if 'APPROVED' in raw else ('blocked' if 'BLOCKED' in raw else 'pending')
        elif upper.startswith('MOTIVO_STATUS:') and not in_body:
            result['motivo_status'] = re.split(r'MOTIVO_STATUS:', stripped, flags=re.IGNORECASE, maxsplit=1)[-1].strip()

    if body_start > 0:
        body_lines = []
        for line in lines[body_start:]:
            ul = line.strip().upper()
            if ul.startswith('STATUS:'):
                raw = re.split(r'STATUS:', line.strip(), flags=re.IGNORECASE, maxsplit=1)[-1].strip().upper()
                result['status'] = 'approved' if 'APPROVED' in raw else ('blocked' if 'BLOCKED' in raw else 'pending')
            elif ul.startswith('MOTIVO_STATUS:'):
                result['motivo_status'] = re.split(r'MOTIVO_STATUS:', line.strip(), flags=re.IGNORECASE, maxsplit=1)[-1].strip()
            else:
                body_lines.append(line)
        result['body'] = '\n'.join(body_lines).strip()

    persona_aliases = {
        'product owner': 'po', 'productowner': 'po',
        'entrevistador de campo': 'fc', 'entrevistador': 'fc', 'field': 'fc',
        'engineering lead': 'el', 'engineeringlead': 'el',
        'developer frontend': 'dev1', 'frontend': 'dev1', 'dev 1': 'dev1',
        'developer backend': 'dev2', 'backend': 'dev2', 'dev 2': 'dev2',
    }

    def normalize(keys):
        out = []
        for k in keys:
            k = k.lower().strip()
            out.append(persona_aliases.get(k, k))
        if 'todos' in out or 'all' in out:
            return ['po', 'fc', 'el', 'dev1', 'dev2']
        return out

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
    extra_instruction: str = '',
) -> EmailMessage:
    if config is None:
        config = ControllerConfig.get_for_user(project.owner)

    api_key = config.anthropic_api_key
    if not api_key:
        from django.conf import settings
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        raise ValueError('Chave da API Anthropic não configurada. Acesse o Controller para configurar.')

    client = anthropic.Anthropic(api_key=api_key)
    history = build_email_history_context(project)

    trigger_block = (
        f'O email abaixo acabou de chegar para você:\n\n{format_email(trigger_email)}'
        if trigger_email else
        'Inicie o próximo passo conforme seu papel no projeto.'
    )

    user_message = f"""{history}

---
INSTRUÇÃO: Você é {PERSONA_NAMES[persona_key]}.
{trigger_block}
{extra_instruction}

Escreva seu próximo email. Use EXATAMENTE este formato:
PARA: [personas separadas por vírgula — use: po, fc, el, dev1, dev2]
CC: [opcional]
ASSUNTO: [assunto claro]
CORPO:
[conteúdo do email em Markdown]

STATUS: [PENDING | APPROVED | BLOCKED]
MOTIVO_STATUS: [breve justificativa do seu status atual]
"""

    # thinking=True → respostas mais elaboradas; thinking=False → modo econômico (padrão)
    thinking_enabled = config and getattr(config, 'enable_thinking', False)
    active_max_tokens = 6000 if thinking_enabled else 1500

    logger.info(
        '→ API Anthropic | modelo=%s | persona=%s | projeto=%d | thinking=%s',
        MODEL, persona_key, project.id, thinking_enabled,
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=active_max_tokens,
            system=SYSTEM_PROMPTS[persona_key],
            messages=[{'role': 'user', 'content': user_message}],
        )
        logger.info(
            '← API Anthropic OK | persona=%s | input=%d | output=%d | stop=%s',
            persona_key, response.usage.input_tokens, response.usage.output_tokens, response.stop_reason,
        )
    except anthropic.APIError as e:
        logger.error('← API Anthropic ERRO | persona=%s | %s', persona_key, e)
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
        defaults={'status': parsed['status'], 'last_concern': parsed.get('motivo_status', '')},
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
