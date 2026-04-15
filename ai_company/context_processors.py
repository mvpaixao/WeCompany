from apps.projects.models import Project


def sidebar_projects(request):
    if request.user.is_authenticated:
        projects = Project.objects.filter(owner=request.user).order_by('-updated_at')[:30]
        return {'sidebar_projects': projects}
    return {'sidebar_projects': []}
