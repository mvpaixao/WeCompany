from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages
from django.utils import timezone

from .models import Project, EmailMessage, PersonaState, GitHubIssue
from apps.controller.models import ControllerConfig
from .tasks import enqueue_flow_step, enqueue_issue_creation


@login_required
def inbox(request):
    projects = Project.objects.filter(owner=request.user).order_by('-updated_at')
    return render(request, 'projects/inbox.html', {'projects': projects})


@login_required
def new_project(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        original_idea = request.POST.get('original_idea', '').strip()
        github_repo = request.POST.get('github_repo', '').strip()

        if not original_idea:
            messages.error(request, 'Por favor, descreva sua ideia.')
            return render(request, 'projects/new_project.html')

        if not title:
            title = original_idea[:80] + ('…' if len(original_idea) > 80 else '')

        project = Project.objects.create(
            owner=request.user,
            title=title,
            original_idea=original_idea,
            github_repo=github_repo,
        )

        # Create initial persona states
        for persona in ['po', 'pm', 'el', 'dev1', 'dev2']:
            PersonaState.objects.create(project=project, persona=persona)

        # Record user's initial message
        EmailMessage.objects.create(
            project=project,
            sender='user',
            recipients=['po'],
            subject=f'Nova ideia: {title}',
            body=original_idea,
            body_html=f'<p>{original_idea}</p>',
            is_read=True,
        )

        # Enqueue first flow step (PO creates Brief)
        enqueue_flow_step(project.id)

        messages.success(request, 'Ideia enviada para a equipe! Aguarde a resposta do Product Owner.')
        return redirect('project_thread', pk=project.pk)

    return render(request, 'projects/new_project.html')


@login_required
def project_thread(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    emails = project.emails.all()
    states = project.states.all()
    issues = project.issues.all()

    # Mark emails as read
    project.emails.filter(is_read=False).update(is_read=True)

    config = ControllerConfig.get_for_user(request.user)

    return render(request, 'projects/email_thread.html', {
        'project': project,
        'emails': emails,
        'persona_states': states,
        'issues': issues,
        'config': config,
    })


@login_required
def submit_feedback(request, pk):
    if request.method != 'POST':
        return redirect('project_thread', pk=pk)

    project = get_object_or_404(Project, pk=pk, owner=request.user)
    feedback = request.POST.get('feedback', '').strip()

    if not feedback:
        messages.error(request, 'Por favor, escreva seu feedback.')
        return redirect('project_thread', pk=pk)

    # Save user feedback as email
    last_email = project.emails.last()
    EmailMessage.objects.create(
        project=project,
        sender='user',
        recipients=['po'],
        subject=f'Re: Feedback do usuário',
        body=feedback,
        body_html=f'<p>{feedback}</p>',
        in_reply_to=last_email,
        is_read=True,
    )

    # Reset all persona states to pending
    project.states.all().update(status='pending', last_concern='')

    # Reactivate project
    project.status = 'active'
    project.save()

    # Enqueue PO response to feedback
    enqueue_flow_step(project.id)

    if request.headers.get('HX-Request'):
        emails = project.emails.all()
        states = project.states.all()
        return render(request, 'projects/_email_list.html', {
            'project': project,
            'emails': emails,
            'persona_states': states,
        })

    return redirect('project_thread', pk=pk)


@login_required
def create_issues(request, pk):
    if request.method != 'POST':
        return redirect('project_thread', pk=pk)

    project = get_object_or_404(Project, pk=pk, owner=request.user)
    enqueue_issue_creation(project.id)
    messages.success(request, 'Criação de Issues no GitHub iniciada!')
    return redirect('project_thread', pk=pk)


@login_required
def force_approve(request, pk):
    """Manual bypass: mark all personas as approved and trigger issue generation."""
    if request.method != 'POST':
        return redirect('project_thread', pk=pk)

    project = get_object_or_404(Project, pk=pk, owner=request.user)
    project.states.all().update(status='approved')

    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject='Aprovação manual pelo usuário',
        body='O usuário forçou a aprovação. Gerando GitHub Issues.',
        body_html='<p><em>O usuário forçou a aprovação. Gerando GitHub Issues.</em></p>',
        is_read=True,
    )

    enqueue_issue_creation(project.id)
    messages.success(request, 'Aprovação forçada. Gerando Issues.')
    return redirect('project_thread', pk=pk)


@login_required
def email_detail(request, pk, email_pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    email = get_object_or_404(EmailMessage, pk=email_pk, project=project)
    email.is_read = True
    email.save(update_fields=['is_read'])
    return render(request, 'projects/_email_card.html', {'email': email, 'project': project})


@login_required
def poll_new_emails(request, pk):
    """HTMX polling: return new emails and optionally refresh status bar."""
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    after_id = int(request.GET.get('after', 0))
    status_only = request.GET.get('status_only') == '1'

    if status_only:
        states = project.states.all()
        return render(request, 'projects/_persona_status_bar.html', {
            'project': project,
            'persona_states': states,
        })

    new_emails = list(project.emails.filter(id__gt=after_id))

    # Nada novo → 204 No Content: HTMX não toca no DOM, scroll preservado
    if not new_emails:
        return HttpResponse(status=204)

    for e in new_emails:
        if not e.is_read:
            e.is_read = True
            e.save(update_fields=['is_read'])

    states = project.states.all()

    return render(request, 'projects/_poll_response.html', {
        'project': project,
        'new_emails': new_emails,
        'persona_states': states,
    })
