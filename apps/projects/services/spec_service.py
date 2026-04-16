"""
Parses spec blocks from dev emails and saves them as ProjectSpec objects.
"""
import re
import logging

from apps.projects.models import Project, ProjectSpec
from apps.projects.services.persona_engine import render_markdown

logger = logging.getLogger(__name__)

# Pattern: ---SPEC-TYPE--- ... ---FIM SPEC-TYPE---
SPEC_PATTERN = re.compile(
    r'---SPEC-(UI|BACKEND|BUSINESS|TECHNICAL)(?:-DELTA)?---\s*(.*?)\s*---FIM SPEC-\1(?:-DELTA)?---',
    re.DOTALL | re.IGNORECASE,
)

SPEC_TYPE_MAP = {
    'UI':        'ui',
    'BACKEND':   'backend',
    'BUSINESS':  'business',
    'TECHNICAL': 'technical',
}


def extract_and_save_specs(
    project: Project,
    version_type: str = 'full',
    version: int = 1,
) -> list[ProjectSpec]:
    """
    Reads all dev1/dev2 emails, extracts spec blocks, saves as ProjectSpec.
    Returns list of saved specs.
    """
    dev_emails = project.emails.filter(sender__in=['dev1', 'dev2']).order_by('created_at')
    saved = []

    for email in dev_emails:
        for match in SPEC_PATTERN.finditer(email.body):
            raw_type = match.group(1).upper()
            body = match.group(2).strip()
            spec_type = SPEC_TYPE_MAP.get(raw_type)
            if not spec_type or not body:
                continue

            # Avoid duplicates for same version
            if ProjectSpec.objects.filter(
                project=project, spec_type=spec_type, version=version
            ).exists():
                continue

            spec = ProjectSpec.objects.create(
                project=project,
                spec_type=spec_type,
                version_type=version_type,
                version=version,
                body=body,
                body_html=render_markdown(body),
            )
            saved.append(spec)
            logger.info('Saved %s spec (v%d, %s) for project %d', spec_type, version, version_type, project.id)

    return saved


def get_latest_specs(project: Project) -> dict:
    """Returns a dict of {spec_type: ProjectSpec} for the latest version."""
    latest_version = project.specs.aggregate(
        v=__import__('django.db.models', fromlist=['Max']).Max('version')
    )['v']
    if not latest_version:
        return {}
    specs = project.specs.filter(version=latest_version)
    return {s.spec_type: s for s in specs}


def get_all_spec_versions(project: Project) -> list[dict]:
    """Returns list of versions, each with their specs."""
    versions = project.specs.values_list('version', flat=True).distinct().order_by('version')
    result = []
    for v in versions:
        specs = project.specs.filter(version=v)
        first = specs.first()
        result.append({
            'version': v,
            'version_type': first.version_type if first else 'full',
            'specs': {s.spec_type: s for s in specs},
            'created_at': first.created_at if first else None,
        })
    return result
