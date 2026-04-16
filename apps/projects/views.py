from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages

from .models import Project, EmailMessage, PersonaState, ProjectSpec
from apps.controller.models import ControllerConfig
from .tasks import enqueue_flow_step
from .services.spec_service import get_all_spec_versions


@login_required
def inbox(request):
    projects = Project.objects.filter(owner=request.user).order_by('-updated_at')
    return render(request, 'projects/inbox.html', {'projects': projects})


@login_required
def new_project(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        original_idea = request.POST.get('original_idea', '').strip()

        if not original_idea:
            messages.error(request, 'Por favor, descreva sua ideia.')
            return render(request, 'projects/new_project.html')

        if not title:
            title = original_idea[:80] + ('…' if len(original_idea) > 80 else '')

        project = Project.objects.create(
            owner=request.user,
            title=title,
            original_idea=original_idea,
        )

        for persona in ['po', 'fc', 'el', 'dev1', 'dev2']:
            PersonaState.objects.create(project=project, persona=persona)

        EmailMessage.objects.create(
            project=project,
            sender='user',
            recipients=['po'],
            subject=f'Nova ideia: {title}',
            body=original_idea,
            body_html=f'<p>{original_idea}</p>',
            is_read=True,
        )

        enqueue_flow_step(project.id)
        messages.success(request, 'Ideia enviada! O Product Owner está preparando o brief.')
        return redirect('project_thread', pk=project.pk)

    return render(request, 'projects/new_project.html')


@login_required
def project_thread(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    emails = project.emails.all()
    states = project.states.all()
    spec_versions = get_all_spec_versions(project)
    config = ControllerConfig.get_for_user(request.user)

    project.emails.filter(is_read=False).update(is_read=True)

    return render(request, 'projects/email_thread.html', {
        'project': project,
        'emails': emails,
        'persona_states': states,
        'spec_versions': spec_versions,
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

    last_email = project.emails.last()
    EmailMessage.objects.create(
        project=project,
        sender='user',
        recipients=['po'],
        subject='Feedback do usuário',
        body=feedback,
        body_html=f'<p>{feedback}</p>',
        in_reply_to=last_email,
        is_read=True,
    )

    # Reset states and reactivate
    project.states.all().update(status='pending', last_concern='')
    project.status = 'active'
    project.save()

    enqueue_flow_step(project.id)

    if request.headers.get('HX-Request'):
        return render(request, 'projects/_email_card.html', {
            'email': project.emails.last(),
            'project': project,
        })
    return redirect('project_thread', pk=pk)


@login_required
def force_approve(request, pk):
    if request.method != 'POST':
        return redirect('project_thread', pk=pk)

    project = get_object_or_404(Project, pk=pk, owner=request.user)
    project.states.all().update(status='approved')

    EmailMessage.objects.create(
        project=project,
        sender='system',
        recipients=[],
        subject='Aprovação manual pelo usuário',
        body='O usuário forçou a aprovação. Gerando especificações.',
        body_html='<p><em>O usuário forçou a aprovação. Gerando especificações.</em></p>',
        is_read=True,
    )

    from .services.flow_manager import _handle_consensus
    from apps.controller.models import ControllerConfig
    config = ControllerConfig.get_for_user(request.user)
    _handle_consensus(project, config)

    messages.success(request, 'Aprovação forçada. Specs geradas.')
    return redirect('project_thread', pk=pk)


@login_required
def poll_new_emails(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)
    after_id = int(request.GET.get('after', 0))
    status_only = request.GET.get('status_only') == '1'

    if status_only:
        return render(request, 'projects/_persona_status_bar.html', {
            'project': project,
            'persona_states': project.states.all(),
        })

    new_emails = list(project.emails.filter(id__gt=after_id))
    if not new_emails:
        return HttpResponse(status=204)

    for e in new_emails:
        if not e.is_read:
            e.is_read = True
            e.save(update_fields=['is_read'])

    return render(request, 'projects/_poll_response.html', {
        'project': project,
        'new_emails': new_emails,
        'persona_states': project.states.all(),
    })
