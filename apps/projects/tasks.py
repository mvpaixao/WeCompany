from django_q.tasks import async_task


def enqueue_flow_step(project_id: int):
    """Enqueue the next flow step without blocking the HTTP request."""
    async_task(
        'apps.projects.services.flow_manager.run_next_step',
        project_id,
        task_name=f'flow_step_{project_id}',
    )


def enqueue_issue_creation(project_id: int):
    """Enqueue GitHub issue creation."""
    async_task(
        'apps.projects.services.github_service.create_issues_from_project_task',
        project_id,
        task_name=f'create_issues_{project_id}',
    )
