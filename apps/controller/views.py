from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import ControllerConfig
from apps.projects.models import Project


@login_required
def controller_dashboard(request):
    config = ControllerConfig.get_for_user(request.user)
    projects = Project.objects.filter(owner=request.user).order_by('-updated_at')

    # Selected project for usage stats
    selected_pk = request.GET.get('project')
    selected_project = None
    if selected_pk:
        selected_project = projects.filter(pk=selected_pk).first()
    if not selected_project and projects.exists():
        selected_project = projects.first()

    return render(request, 'controller/dashboard.html', {
        'config': config,
        'projects': projects,
        'selected_project': selected_project,
    })


@login_required
def save_config(request):
    if request.method != 'POST':
        return redirect('controller')

    config = ControllerConfig.get_for_user(request.user)

    # Only update key fields if non-empty (avoid erasing with blank)
    anthropic_key = request.POST.get('anthropic_api_key', '').strip()
    if anthropic_key:
        config.anthropic_api_key = anthropic_key

    github_token = request.POST.get('github_token', '').strip()
    if github_token:
        config.github_token = github_token

    config.github_default_repo = request.POST.get('github_default_repo', '').strip()

    try:
        config.max_tokens_per_project = int(request.POST.get('max_tokens_per_project', 100_000))
        config.max_cost_usd_per_project = float(request.POST.get('max_cost_usd_per_project', 5.0))
        config.controller_check_every_n_tokens = int(request.POST.get('controller_check_every_n_tokens', 5_000))
        config.max_rounds_per_flow = int(request.POST.get('max_rounds_per_flow', 20))
    except (ValueError, TypeError):
        messages.error(request, 'Valores numéricos inválidos.')
        return redirect('controller')

    config.auto_create_github_issues = 'auto_create_github_issues' in request.POST
    config.save()

    messages.success(request, 'Configurações salvas com sucesso!')
    return redirect('controller')
