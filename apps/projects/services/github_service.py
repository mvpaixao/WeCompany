"""
Parses GitHub Issues from dev emails and creates them via PyGitHub.
"""
import re
import logging

from github import Github, GithubException

from apps.projects.models import Project, GitHubIssue, EmailMessage
from apps.controller.models import ControllerConfig

logger = logging.getLogger(__name__)

ISSUE_PATTERN = re.compile(
    r'---ISSUE---\s*(.*?)\s*---FIM ISSUE---',
    re.DOTALL | re.IGNORECASE,
)

TITLE_PATTERN = re.compile(r'\*\*Título:\*\*\s*(.+)', re.IGNORECASE)
LABELS_PATTERN = re.compile(r'\*\*Labels:\*\*\s*(.+)', re.IGNORECASE)
DESC_PATTERN = re.compile(r'\*\*Descrição:\*\*\s*(.*?)(?=\*\*Critérios|\*\*Notas|$)', re.DOTALL | re.IGNORECASE)
CRITERIA_PATTERN = re.compile(r'\*\*Critérios de Aceitação:\*\*\s*(.*?)(?=\*\*Notas|$)', re.DOTALL | re.IGNORECASE)
NOTES_PATTERN = re.compile(r'\*\*Notas Técnicas:\*\*\s*(.*?)$', re.DOTALL | re.IGNORECASE)


def parse_issues_from_email(body: str) -> list[dict]:
    issues = []
    for match in ISSUE_PATTERN.finditer(body):
        content = match.group(1)

        title_m = TITLE_PATTERN.search(content)
        labels_m = LABELS_PATTERN.search(content)
        desc_m = DESC_PATTERN.search(content)
        criteria_m = CRITERIA_PATTERN.search(content)
        notes_m = NOTES_PATTERN.search(content)

        if not title_m:
            continue

        title = title_m.group(1).strip()
        labels = [l.strip() for l in labels_m.group(1).split(',')] if labels_m else []
        description = desc_m.group(1).strip() if desc_m else ''
        criteria = criteria_m.group(1).strip() if criteria_m else ''
        notes = notes_m.group(1).strip() if notes_m else ''

        body_parts = []
        if description:
            body_parts.append(f'## Descrição\n{description}')
        if criteria:
            body_parts.append(f'## Critérios de Aceitação\n{criteria}')
        if notes:
            body_parts.append(f'## Notas Técnicas\n{notes}')
        body_parts.append('\n---\n*Issue gerada pelo AI Company Simulator*')

        issues.append({
            'title': title,
            'body': '\n\n'.join(body_parts),
            'labels': labels,
        })

    return issues


def create_issues_from_project_task(project_id: int) -> None:
    """Entry point for Django Q task."""
    try:
        project = Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        logger.error('Project %d not found', project_id)
        return

    config = ControllerConfig.get_for_user(project.owner)
    create_issues_from_project(project, config)


def create_issues_from_project(project: Project, config: ControllerConfig) -> list[GitHubIssue]:
    github_token = config.github_token
    repo_name = project.github_repo or config.github_default_repo

    if not github_token:
        _system_message(project, 'GitHub Token não configurado. Acesse o Controller para configurar.')
        return []

    if not repo_name:
        _system_message(project, 'Repositório GitHub não configurado. Defina no projeto ou no Controller.')
        return []

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)
    except GithubException as e:
        _system_message(project, f'Erro ao acessar o repositório "{repo_name}": {e}')
        return []

    dev_emails = project.emails.filter(sender__in=['dev1', 'dev2']).order_by('created_at')
    created = []

    for email in dev_emails:
        issues_data = parse_issues_from_email(email.body)
        for issue_data in issues_data:
            # Check for duplicates
            if GitHubIssue.objects.filter(project=project, title=issue_data['title']).exists():
                continue
            try:
                gh_issue = repo.create_issue(
                    title=issue_data['title'],
                    body=issue_data['body'],
                    labels=issue_data.get('labels', []),
                )
                db_issue = GitHubIssue.objects.create(
                    project=project,
                    github_issue_number=gh_issue.number,
                    github_url=gh_issue.html_url,
                    title=issue_data['title'],
                    body=issue_data['body'],
                    labels=issue_data.get('labels', []),
                )
                created.append(db_issue)
                logger.info('Created GitHub issue #%d for project %d', gh_issue.number, project.id)
            except GithubException as e:
                logger.error('Failed to create issue "%s": %s', issue_data['title'], e)

    if created:
        urls = '\n'.join(f'- [{i.title}]({i.github_url})' for i in created)
        _system_message(
            project,
            f'**{len(created)} Issue(s) criada(s) no GitHub:**\n\n{urls}',
        )
        project.status = 'completed'
        project.save(update_fields=['status', 'updated_at'])
    else:
        _system_message(project, 'Nenhuma issue encontrada nos emails dos Developers para criar no GitHub.')

    return created


def _system_message(project: Project, body: str) -> None:
    from apps.projects.services.persona_engine import render_markdown
    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject='GitHub Issues',
        body=body,
        body_html=render_markdown(body),
        is_read=False,
    )
