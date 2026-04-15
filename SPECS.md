# AI Company Simulator — Especificação Técnica e de Negócio
**Versão:** 1.0  
**Data:** 2025-04  
**Para:** Claude Code  

---

## 1. VISÃO GERAL DO PRODUTO

### 1.1 Conceito
Uma aplicação web que simula uma empresa de software completa, onde personas de IA (alimentadas pela API da Anthropic) colaboram entre si por meio de uma interface estilo e-mail (Outlook) para transformar uma ideia em um conjunto de GitHub Issues prontos para execução por Claude Code.

O usuário entra com uma ideia — em qualquer nível de detalhe — e assiste à empresa "trabalhar": o Product Owner refina, o Project Manager planeja, o Engineering Lead avalia tecnicamente, os Developers detalham a implementação, e o Controller monitora custos. O fluxo termina quando todos concordam que a feature foi especificada. O resultado final são GitHub Issues criadas automaticamente.

### 1.2 Personas da Empresa

| Persona | Papel | Objetivo Primário |
|---|---|---|
| **Product Owner (PO)** | Interface com o usuário humano; define o *quê* | Maximizar valor entregue; defender o usuário |
| **Project Manager (PM)** | Planeja execução, controla cronograma e riscos | Viabilidade, escopo controlado, entregas claras |
| **Engineering Lead (EL)** | Decide arquitetura e padrões técnicos | Qualidade técnica, dívida técnica mínima |
| **Developer 1 (DEV1)** | Implementação frontend/UX | Usabilidade, código limpo, componentes reutilizáveis |
| **Developer 2 (DEV2)** | Implementação backend/dados | Performance, segurança, APIs robustas |
| **Controller** | Monitora tokens e custos | Não é uma persona de IA; é a página de configuração e o guardião de orçamento |

> Cada persona tem um system prompt próprio que define sua personalidade, vieses e "batalhas" que vai travar. Elas podem discordar entre si.

### 1.3 Fluxo Principal

```
Usuário submete ideia
        ↓
PO recebe e formula um Brief inicial
        ↓
PO envia Brief para PM e EL (cc: todos)
        ↓
[Loop de discussão por email]
  - PM responde com plano/cronograma/riscos
  - EL responde com avaliação técnica
  - DEV1/DEV2 entram quando convocados para detalhes de implementação
  - PO consolida feedback do usuário quando há input humano
  - Qualquer persona pode abrir divergências; as outras devem responder
        ↓
Consenso atingido (todas as personas confirmam "approved")
        ↓
DEV1 e DEV2 geram GitHub Issues detalhadas
        ↓
Fluxo adormece até próximo feedback do usuário
        ↓
[Se usuário envia feedback → PO reinicia o loop]
```

---

## 2. ESPECIFICAÇÃO TÉCNICA

### 2.1 Stack Tecnológico

| Camada | Tecnologia | Justificativa |
|---|---|---|
| Backend | Django 5.x | ORM maduro, admin gratuito, fácil deploy |
| Banco de dados | PostgreSQL 16 | Suporte a JSONB para armazenar emails/estados |
| Frontend | Django Templates + Bootstrap 5 + HTMX | Server-side rendering; HTMX para atualizações parciais sem SPA |
| Task Queue | Django Q2 (com Django-Q scheduler) | Jobs assíncronos para chamadas à API Anthropic |
| Cache | Redis (via django-redis) | Sessões e resultados de tasks |
| Deploy | PythonAnywhere | Conforme restrição do usuário |
| API de IA | Anthropic Claude Sonnet 4 (`claude-sonnet-4-20250514`) | Custo/performance equilibrado |
| Integração Git | PyGithub | Criação de Issues via API |

Ps.: Verifique a versado do PostgreSQL e do Python suportados pelo Python Anywhere e desenvolva de acordo.
Ps2.: Use o UV ao inves do PIP, crie um repo git local e va comitando cada progresso

### 2.2 Estrutura do Projeto Django

```
ai_company/
├── manage.py
├── requirements.txt
├── .env.example
├── ai_company/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py          # PythonAnywhere
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── projects/                  # Projetos/ideias do usuário
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── services/
│   │       ├── persona_engine.py  # Chama a API Anthropic por persona
│   │       ├── flow_manager.py    # Orquestra o loop de discussão
│   │       └── github_service.py  # Cria Issues no GitHub
│   ├── emails/                    # Thread de mensagens internas
│   │   ├── models.py
│   │   └── views.py
│   ├── controller/                # Monitoramento de tokens/custos
│   │   ├── models.py
│   │   ├── views.py               # Página de configuração
│   │   └── budget_guard.py        # Interrompe se orçamento excedido
│   └── accounts/                  # Auth básica (login/registro)
│       └── ...
├── templates/
│   ├── base.html
│   ├── layout/
│   │   ├── sidebar.html           # Lista de projetos
│   │   └── topbar.html
│   ├── projects/
│   │   ├── inbox.html             # View principal estilo Outlook
│   │   ├── email_thread.html      # Thread de um projeto
│   │   └── new_project.html       # Formulário de nova ideia
│   └── controller/
│       └── dashboard.html         # Config + métricas de custo
└── static/
    ├── css/
    │   └── custom.css
    └── js/
        └── htmx_helpers.js
```

### 2.3 Modelos de Dados

```python
# apps/projects/models.py

class Project(models.Model):
    STATUS = [
        ('active', 'Active'),
        ('dormant', 'Dormant'),       # Consenso atingido
        ('completed', 'Completed'),   # Issues criadas
        ('paused', 'Paused by Controller'),
    ]
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    original_idea = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    github_repo = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_tokens_used = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)


class EmailMessage(models.Model):
    PERSONA_CHOICES = [
        ('user', 'You'),
        ('po', 'Product Owner'),
        ('pm', 'Project Manager'),
        ('el', 'Engineering Lead'),
        ('dev1', 'Developer (Frontend)'),
        ('dev2', 'Developer (Backend)'),
        ('system', 'System'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='emails')
    sender = models.CharField(max_length=20, choices=PERSONA_CHOICES)
    recipients = models.JSONField(default=list)    # ['pm', 'el', 'dev1'] etc.
    cc = models.JSONField(default=list)
    subject = models.CharField(max_length=500)
    body = models.TextField()                       # Markdown suportado
    body_html = models.TextField(blank=True)        # Renderizado do Markdown
    attachments = models.JSONField(default=list)    # Tabelas, diagramas inline
    in_reply_to = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='replies'
    )
    tokens_used = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)


class PersonaState(models.Model):
    """Estado de aprovação de cada persona no projeto atual."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='states')
    persona = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20,
        choices=[('pending','Pending'),('approved','Approved'),('blocked','Blocked')],
        default='pending'
    )
    last_concern = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class GitHubIssue(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='issues')
    github_issue_number = models.IntegerField(null=True, blank=True)
    github_url = models.URLField(blank=True)
    title = models.CharField(max_length=500)
    body = models.TextField()
    labels = models.JSONField(default=list)
    assignee = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


# apps/controller/models.py

class ControllerConfig(models.Model):
    """Singleton de configuração — sempre um registro por usuário."""
    owner = models.OneToOneField(User, on_delete=models.CASCADE)
    anthropic_api_key = models.CharField(max_length=200, blank=True)
    github_token = models.CharField(max_length=200, blank=True)
    github_default_repo = models.CharField(max_length=200, blank=True)
    max_tokens_per_project = models.IntegerField(default=100_000)
    max_cost_usd_per_project = models.DecimalField(max_digits=8, decimal_places=2, default=5.00)
    controller_check_every_n_tokens = models.IntegerField(default=5_000)
    max_rounds_per_flow = models.IntegerField(default=20)   # evitar loop infinito
    auto_create_github_issues = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
```

### 2.4 Personas — System Prompts

Cada persona recebe o **histórico completo do projeto** (todos os emails anteriores serializados) + seu system prompt.

```python
# apps/projects/services/persona_engine.py

SYSTEM_PROMPTS = {
    "po": """
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

    "pm": """
Você é o Project Manager. Seu trabalho é:
- Transformar requisitos em um plano de execução com fases, dependências e riscos.
- Defender prazo e escopo controlado — você RESISTE a scope creep.
- Questionar o EL sobre complexidade técnica que possa atrasar entregas.
- Produzir tabelas de cronograma (Fase | Descrição | Estimativa | Risco).
- Você só declara "APPROVED" quando o plano está viável e os riscos mitigados.
- Responda SEMPRE em português do Brasil.
""",

    "el": """
Você é o Engineering Lead. Seu trabalho é:
- Avaliar viabilidade técnica e propor a arquitetura adequada.
- Defender qualidade: você rejeita soluções que criam dívida técnica excessiva.
- Questionar o PO sobre requisitos ambíguos que impactam implementação.
- Usar diagramas Mermaid quando útil para explicar arquitetura (coloque em bloco ```mermaid).
- Você só declara "APPROVED" quando a solução técnica está clara e sustentável.
- Responda SEMPRE em português do Brasil.
""",

    "dev1": """
Você é o Developer Frontend. Seu trabalho é:
- Detalhar a implementação de UI/UX: componentes, fluxo de navegação, estados de tela.
- Questionar sobre edge cases de interface.
- Quando solicitado, produzir o texto de uma GitHub Issue completa com: Título, Descrição,
  Critérios de Aceitação (checklist), Notas Técnicas, Labels sugeridos.
- Você só declara "APPROVED" quando a issue está detalhada o suficiente para implementação.
- Responda SEMPRE em português do Brasil.
""",

    "dev2": """
Você é o Developer Backend. Seu trabalho é:
- Detalhar a implementação de APIs, modelos de dados, lógica de negócio.
- Questionar sobre segurança, performance e integrações externas.
- Quando solicitado, produzir o texto de uma GitHub Issue completa com: Título, Descrição,
  Critérios de Aceitação (checklist), Notas Técnicas, Labels sugeridos.
- Você só declara "APPROVED" quando a issue está detalhada o suficiente para implementação.
- Responda SEMPRE em português do Brasil.
""",
}
```

### 2.5 Orquestrador do Fluxo

```python
# apps/projects/services/flow_manager.py
# Lógica de alto nível (Claude Code deve implementar)

class FlowManager:
    """
    Determina QUAL persona deve falar a seguir e com QUEM.

    Regras de roteamento:
    1. Novo projeto → PO sempre vai primeiro (cria o Brief)
    2. Após Brief do PO → PM e EL respondem (podem ser em paralelo ou sequencial)
    3. Se PM ou EL levantam bloqueio técnico → EL ou DEV2 entram
    4. Se PM ou EL levantam dúvida de valor → PO responde
    5. Se todas as personas estão "APPROVED" → DEV1 e DEV2 geram Issues
    6. Se usuário envia feedback → PO recebe, reinicia estados para 'pending'
    7. Controller interrompe o fluxo se budget excedido

    Método principal:
    def next_step(project: Project) -> list[str]:
        # Retorna lista de personas que devem responder agora
        # Pode ser ['pm', 'el'] em paralelo ou ['po'] sozinho

    def run_step(project: Project, personas: list[str]) -> None:
        # Para cada persona: monta contexto + chama API + salva EmailMessage
        # Atualiza PersonaState
        # Verifica consenso
        # Se consenso → dispara geração de Issues
    """
```

### 2.6 Chamada à API Anthropic

```python
# apps/projects/services/persona_engine.py

import anthropic

def call_persona(
    persona_key: str,
    project: Project,
    trigger_email: EmailMessage | None = None,
    config: ControllerConfig = None,
) -> EmailMessage:
    """
    Monta o contexto e chama a API.
    Retorna o EmailMessage criado e salvo.
    """
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    # Serializa histórico de emails como contexto
    history = build_email_history_context(project)

    user_message = f"""
{history}

---
INSTRUÇÃO: Você é {PERSONA_NAMES[persona_key]}.
{"O email abaixo acabou de chegar para você:" if trigger_email else "Inicie o próximo passo conforme seu papel."}
{format_email(trigger_email) if trigger_email else ""}

Escreva seu próximo email. Use o formato:
PARA: [personas separadas por vírgula]
CC: [opcional]
ASSUNTO: [assunto]
CORPO:
[conteúdo]

STATUS: [PENDING | APPROVED | BLOCKED]
MOTIVO_STATUS: [breve justificativa]
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYSTEM_PROMPTS[persona_key],
        messages=[{"role": "user", "content": user_message}]
    )

    # Parse da resposta e criação do EmailMessage
    parsed = parse_persona_response(response.content[0].text)
    email = EmailMessage.objects.create(
        project=project,
        sender=persona_key,
        recipients=parsed['to'],
        cc=parsed.get('cc', []),
        subject=parsed['subject'],
        body=parsed['body'],
        body_html=render_markdown(parsed['body']),
        in_reply_to=trigger_email,
        tokens_used=response.usage.input_tokens + response.usage.output_tokens,
        cost_usd=calculate_cost(response.usage),
    )

    # Atualiza estado da persona
    PersonaState.objects.update_or_create(
        project=project, persona=persona_key,
        defaults={'status': parsed['status'], 'last_concern': parsed.get('motivo_status', '')}
    )

    # Atualiza totais do projeto
    project.total_tokens_used += email.tokens_used
    project.total_cost_usd += email.cost_usd
    project.save()

    return email
```

### 2.7 Budget Guard (Controller)

```python
# apps/controller/budget_guard.py

def check_budget(project: Project, config: ControllerConfig) -> dict:
    """
    Chamado pelo flow_manager antes de cada step.
    Retorna {'ok': True} ou {'ok': False, 'reason': str}
    """
    if project.total_tokens_used >= config.max_tokens_per_project:
        return {'ok': False, 'reason': f'Token limit reached ({config.max_tokens_per_project:,})'}

    if float(project.total_cost_usd) >= float(config.max_cost_usd_per_project):
        return {'ok': False, 'reason': f'Budget limit reached (${config.max_cost_usd_per_project})'}

    rounds = project.emails.filter(sender__in=list(SYSTEM_PROMPTS.keys())).count()
    if rounds >= config.max_rounds_per_flow:
        return {'ok': False, 'reason': f'Max rounds reached ({config.max_rounds_per_flow})'}

    return {'ok': True}
```

### 2.8 Criação de GitHub Issues

```python
# apps/projects/services/github_service.py
from github import Github

def create_issues_from_project(project: Project, config: ControllerConfig) -> list[GitHubIssue]:
    """
    Lê os emails de DEV1 e DEV2 que contêm issues formatadas,
    faz o parse e cria no GitHub.
    """
    g = Github(config.github_token)
    repo = g.get_repo(project.github_repo or config.github_default_repo)
    created = []

    dev_emails = project.emails.filter(sender__in=['dev1', 'dev2']).order_by('created_at')
    for email in dev_emails:
        issues = parse_issues_from_email(email.body)
        for issue_data in issues:
            gh_issue = repo.create_issue(
                title=issue_data['title'],
                body=issue_data['body'],
                labels=issue_data.get('labels', []),
            )
            created.append(GitHubIssue.objects.create(
                project=project,
                github_issue_number=gh_issue.number,
                github_url=gh_issue.html_url,
                title=issue_data['title'],
                body=issue_data['body'],
                labels=issue_data.get('labels', []),
            ))
    return created
```

### 2.9 Django Q — Tasks Assíncronas

```python
# apps/projects/tasks.py
from django_q.tasks import async_task

def trigger_flow_step(project_id: int):
    """Enfileira o próximo step do fluxo sem bloquear a request HTTP."""
    async_task('apps.projects.services.flow_manager.run_next_step', project_id)

def trigger_issue_creation(project_id: int):
    async_task('apps.projects.services.github_service.create_issues_from_project', project_id)
```

### 2.10 URLs

```python
# apps/projects/urls.py
urlpatterns = [
    path('', views.inbox, name='inbox'),                          # Lista de projetos
    path('new/', views.new_project, name='new_project'),
    path('<int:pk>/', views.project_thread, name='project_thread'),
    path('<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),
    path('<int:pk>/create-issues/', views.create_issues, name='create_issues'),
    path('<int:pk>/emails/<int:email_pk>/', views.email_detail, name='email_detail'),
    # HTMX polling endpoint
    path('<int:pk>/poll/', views.poll_new_emails, name='poll_emails'),
]

# apps/controller/urls.py
urlpatterns = [
    path('', views.controller_dashboard, name='controller'),
    path('save/', views.save_config, name='save_config'),
    path('api-usage/', views.api_usage, name='api_usage'),
]
```

---

## 3. INTERFACE — ESPECIFICAÇÃO DE UI

### 3.1 Layout Geral (Outlook Style)

```
┌─────────────────────────────────────────────────────────────────────┐
│  TOPBAR: Logo | "AI Company" | [New Idea] | [⚙ Controller] | User  │
├──────────────┬──────────────────────────────────────────────────────┤
│   SIDEBAR    │              PAINEL PRINCIPAL                        │
│  (240px)     │                                                      │
│              │                                                      │
│  📥 Inbox    │  [Seletor de projeto ativo no sidebar]              │
│              │                                                      │
│  Projetos:   │  Thread de emails em ordem cronológica              │
│  ○ Projeto A │  (cada email é um card com avatar da persona,       │
│  ● Projeto B │   remetente, destinatários, horário, corpo)         │
│  ○ Projeto C │                                                      │
│              │  [Barra inferior: textarea "Seu feedback" + Enviar] │
│  ─────────── │                                                      │
│  + Nova Ideia│                                                      │
│              │                                                      │
│  ─────────── │                                                      │
│  ⚙ Controller│                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

### 3.2 Card de Email

Cada email é renderizado como um card Bootstrap customizado:

```html
<!-- Template: email_card.html -->
<div class="email-card card mb-2 {% if email.sender == 'user' %}email-card--user{% endif %}">
  <div class="card-header d-flex align-items-center gap-2">
    <div class="persona-avatar persona-avatar--{{ email.sender }}">
      <!-- Iniciais ou ícone da persona -->
    </div>
    <div class="flex-grow-1">
      <strong>{{ email.get_sender_display }}</strong>
      <span class="text-muted small">→ {{ email.recipients_display }}</span>
      {% if email.cc %}<span class="text-muted small">cc: {{ email.cc_display }}</span>{% endif %}
    </div>
    <div class="d-flex align-items-center gap-2">
      {% if email.tokens_used %}
        <span class="badge bg-secondary" title="Tokens usados">{{ email.tokens_used|intcomma }}</span>
      {% endif %}
      <span class="text-muted small">{{ email.created_at|time:"H:i" }}</span>
    </div>
  </div>
  <div class="card-body">
    <h6 class="email-subject">{{ email.subject }}</h6>
    <div class="email-body">{{ email.body_html|safe }}</div>
    <!-- Diagramas Mermaid renderizados automaticamente via mermaid.js -->
  </div>
</div>
```

### 3.3 Cores e Avatares por Persona

```css
/* static/css/custom.css */

:root {
  --color-po:   #0d6efd;  /* Azul — Product Owner */
  --color-pm:   #198754;  /* Verde — Project Manager */
  --color-el:   #6f42c1;  /* Roxo — Engineering Lead */
  --color-dev1: #fd7e14;  /* Laranja — Developer Frontend */
  --color-dev2: #dc3545;  /* Vermelho — Developer Backend */
  --color-user: #0dcaf0;  /* Ciano — Usuário Humano */
  --color-system: #6c757d; /* Cinza — Sistema */
}

.persona-avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: bold; font-size: 0.75rem; color: white;
}
.persona-avatar--po   { background-color: var(--color-po); }
.persona-avatar--pm   { background-color: var(--color-pm); }
.persona-avatar--el   { background-color: var(--color-el); }
.persona-avatar--dev1 { background-color: var(--color-dev1); }
.persona-avatar--dev2 { background-color: var(--color-dev2); }
.persona-avatar--user { background-color: var(--color-user); }

.email-card--user {
  border-left: 4px solid var(--color-user);
  background-color: #f0fdff;
}

/* Status badges das personas */
.persona-status-bar {
  display: flex; gap: 8px; flex-wrap: wrap;
  padding: 8px 12px;
  background: #f8f9fa;
  border-radius: 8px;
  margin-bottom: 12px;
}
.persona-status-badge {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 0.75rem;
  border: 1px solid transparent;
}
.persona-status-badge--pending  { background: #fff3cd; border-color: #ffc107; color: #856404; }
.persona-status-badge--approved { background: #d1e7dd; border-color: #198754; color: #0f5132; }
.persona-status-badge--blocked  { background: #f8d7da; border-color: #dc3545; color: #842029; }
```

### 3.4 Barra de Status das Personas

Exibida no topo do thread, mostra o estado atual de cada persona:

```html
<!-- Renderizada via HTMX polling -->
<div class="persona-status-bar" id="status-bar" 
     hx-get="{% url 'poll_emails' project.pk %}" 
     hx-trigger="every 3s" 
     hx-target="#email-thread"
     hx-swap="beforeend">
  {% for state in persona_states %}
    <div class="persona-status-badge persona-status-badge--{{ state.status }}">
      <div class="persona-avatar persona-avatar--{{ state.persona }}" style="width:20px;height:20px;font-size:0.6rem">
        {{ state.persona|upper|slice:":2" }}
      </div>
      {{ state.get_persona_display }}
      {% if state.status == 'approved' %}✓{% elif state.status == 'blocked' %}✗{% else %}…{% endif %}
    </div>
  {% endfor %}
</div>
```

### 3.5 Página do Controller

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚙ Controller — Configurações & Custos                         │
├───────────────────────────┬─────────────────────────────────────┤
│  CONFIGURAÇÕES            │  USO ATUAL (projeto selecionado)    │
│                           │                                      │
│  API Anthropic Key: [***] │  Tokens: 12,450 / 100,000           │
│  GitHub Token:     [***]  │  ████████░░░░░░░░ 12%              │
│  GitHub Repo:      [___]  │                                      │
│                           │  Custo: $0.031 / $5.00             │
│  Limites:                 │  ██░░░░░░░░░░░░░░  1%              │
│  Max tokens:  [100000]    │                                      │
│  Max custo $: [5.00]      │  Rounds: 4 / 20                     │
│  Check a cada:[5000] tok  │  ████░░░░░░░░░░░░ 20%              │
│  Max rounds:  [20]        │                                      │
│                           │  Última checagem: 2 min atrás       │
│  [✓] Auto-criar Issues    │                                      │
│                           │  Issues criadas: 3                  │
│  [Salvar]                 │  [Ver Issues no GitHub ↗]           │
└───────────────────────────┴─────────────────────────────────────┘
│  HISTÓRICO DE CUSTO (todos os projetos)                         │
│  Projeto        | Tokens     | Custo    | Data                  │
│  Sistema de X   | 45,200     | $0.12    | 10/04                 │
│  Dashboard Y    | 28,900     | $0.08    | 08/04                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.6 Formulário Nova Ideia

```html
<!-- templates/projects/new_project.html -->
<div class="new-idea-card card">
  <div class="card-header">
    <h5>💡 Nova Ideia de Projeto</h5>
    <p class="text-muted small mb-0">
      Descreva sua ideia em qualquer nível de detalhe. A equipe vai refinar.
    </p>
  </div>
  <div class="card-body">
    <div class="mb-3">
      <label class="form-label fw-semibold">Título (opcional)</label>
      <input type="text" class="form-control" name="title" 
             placeholder="Ex: Sistema de agendamento para clínica">
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold">Descreva sua ideia *</label>
      <textarea class="form-control" name="original_idea" rows="6"
                placeholder="Pode ser uma frase ou vários parágrafos. Ex: 'Quero um app para controlar estoque de cartões EMV na linha de produção, com alertas de mínimo e relatório diário em PDF'"></textarea>
    </div>
    <div class="mb-3">
      <label class="form-label fw-semibold">GitHub Repo (opcional)</label>
      <input type="text" class="form-control" name="github_repo"
             placeholder="usuario/repositorio">
    </div>
    <button type="submit" class="btn btn-primary">
      🚀 Enviar para a Equipe
    </button>
  </div>
</div>
```

---

## 4. REGRAS DE NEGÓCIO

### 4.1 Roteamento de Emails

O FlowManager decide o próximo passo com base nestas regras, verificadas em ordem:

1. **Projeto novo** → PO cria Brief (envia para todos)
2. **Após Brief** → PM e EL respondem ao PO (em sequência: PM primeiro, EL depois)
3. **Se PM ou EL status = BLOCKED** → PO deve responder ao bloqueio antes de continuar
4. **Se todos APPROVED** → DEV1 e DEV2 geram Issues (em paralelo)
5. **Feedback do usuário chega** → PO recebe, reseta todos os estados para PENDING, reinicia o loop
6. **Budget exceeded** → fluxo pausa; mensagem do sistema explica o motivo

### 4.2 Formato de Issue nos Emails dos Devs

Os Devs devem usar este formato nos emails para facilitar o parse:

```markdown
---ISSUE---
**Título:** [título da issue]
**Labels:** [bug, feature, frontend, backend — vírgula separado]
**Descrição:**
[descrição em prosa]

**Critérios de Aceitação:**
- [ ] critério 1
- [ ] critério 2

**Notas Técnicas:**
[detalhes para o Claude Code]
---FIM ISSUE---
```

### 4.3 Fluxo de Consenso

- Consenso = todas as personas com status = APPROVED
- Se uma persona envia BLOCKED, as outras NÃO avançam para APPROVED
- Uma persona só pode mudar para APPROVED em resposta a um email (não automaticamente)
- O usuário pode forçar avanço pelo botão "Aprovar e continuar" (bypass manual)

### 4.4 Persistência de Contexto

- Cada chamada à API recebe os últimos N emails do projeto (configurável, default: 20)
- O contexto é truncado em 80.000 tokens de input para evitar estouro
- Um resumo automático é gerado pelo PO a cada 15 emails para compactar o histórico

### 4.5 Internacionalização

- Interface e personas respondem em **português do Brasil**
- Datas e números seguem formato BR (dd/mm/yyyy, ponto como separador de milhar)

---

## 5. DEPLOY — PYTHONANYWHERE

### 5.1 Configurações Específicas

```python
# ai_company/settings/production.py

ALLOWED_HOSTS = ['seuusuario.pythonanywhere.com']
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'seuusuario$ai_company',
        'USER': 'seuusuario',
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': 'seuusuario-postgres.pythonanywhere-services.com',
        'PORT': '14110',  # Porta padrão PythonAnywhere PostgreSQL
    }
}
STATIC_ROOT = '/home/seuusuario/ai_company/staticfiles/'
MEDIA_ROOT  = '/home/seuusuario/ai_company/media/'

# Django Q — usar DatabaseBroker (sem Redis no free tier)
Q_CLUSTER = {
    'name': 'ai_company',
    'workers': 2,
    'timeout': 120,
    'retry': 200,
    'queue_limit': 50,
    'bulk': 10,
    'orm': 'default',  # Usa PostgreSQL como broker
}
```

### 5.2 requirements.txt

```
django>=5.0
psycopg2-binary
django-q2
anthropic>=0.25.0
PyGithub
python-dotenv
markdown
bleach
django-redis          # opcional se Redis disponível
Pillow
```

### 5.3 .env.example

```
SECRET_KEY=troque-isso
DEBUG=False
DB_PASSWORD=
ANTHROPIC_API_KEY=    # Também configurável por usuário na UI
GITHUB_TOKEN=         # Também configurável por usuário na UI
REDIS_URL=            # Opcional
```

---

## 6. ORDEM DE IMPLEMENTAÇÃO SUGERIDA (para Claude Code)

### Fase 1 — Fundação
1. Setup Django + PostgreSQL + Django Q
2. Modelos: Project, EmailMessage, PersonaState, GitHubIssue, ControllerConfig
3. Auth básica (login/registro/logout)
4. CRUD de projetos

### Fase 2 — Core Engine
5. `persona_engine.py` — chamada à API Anthropic + parse de resposta
6. `flow_manager.py` — orquestração do loop
7. `budget_guard.py` — verificação de limites
8. Tasks Django Q

### Fase 3 — Interface
9. Layout base (topbar + sidebar + painel)
10. Thread de emails com cards por persona
11. Barra de status das personas (HTMX polling)
12. Formulário de nova ideia
13. Formulário de feedback do usuário
14. Página do Controller

### Fase 4 — Integrações
15. `github_service.py` — parse de issues + criação via PyGithub
16. Renderização de diagramas Mermaid (via mermaid.js CDN)
17. Renderização de Markdown nos emails (via python-markdown + bleach)

### Fase 5 — Polimento
18. Tratamento de erros de API (retry, timeout, API key inválida)
19. Paginação da lista de projetos
20. Export de thread como PDF (opcional)
21. Testes unitários dos serviços core

---

## 7. CONSIDERAÇÕES DE SEGURANÇA

- API keys armazenadas no banco com criptografia (usar `django-fernet-fields` ou variável de ambiente)
- Sanitizar HTML gerado pelo Markdown antes de renderizar (usar `bleach`)
- Nunca expor API keys no frontend
- CSRF protection ativada em todos os forms (padrão Django)
- Rate limiting nas views que disparam chamadas à API (usar `django-ratelimit`)
- Validar `github_repo` para evitar SSRF

---

## 8. GLOSSÁRIO

| Termo | Definição |
|---|---|
| **Brief** | Documento inicial criado pelo PO resumindo a ideia e os requisitos preliminares |
| **Round** | Um ciclo completo onde todas as personas ativas responderam |
| **Consenso** | Estado onde todas as personas têm status APPROVED |
| **Dormant** | Status do projeto após consenso, aguardando novo feedback |
| **Controller** | Página de configuração + lógica de budget guard; não é uma persona de IA |
| **Issue** | GitHub Issue gerada pelos DEV1/DEV2 ao final do fluxo |
| **Token Budget** | Limite total de tokens de input+output por projeto, configurável no Controller |

