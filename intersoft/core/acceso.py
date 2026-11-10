def correo_del_intento(request, credentials):
    """Correo con el que se intenta ingresar, en minúsculas, para django-axes.

    Sin esto, cambiar mayúsculas (Ana@ y ana@) contaría como cuentas distintas y
    permitiría saltarse el límite de intentos.
    """
    correo = (credentials or {}).get("username") or request.POST.get("username", "")
    return correo.strip().lower()
