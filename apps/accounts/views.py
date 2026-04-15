from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages


def register(request):
    if request.user.is_authenticated:
        return redirect('inbox')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Conta criada com sucesso! Bem-vindo ao AI Company.')
            return redirect('inbox')
    else:
        form = UserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})
