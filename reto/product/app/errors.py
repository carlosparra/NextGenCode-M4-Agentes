"""Errores compartidos del producto.

Vive aparte para que ``config`` y ``auth`` lo usen sin importarse entre si.
"""


class ConfigError(ValueError):
    """Error de configuracion que impide arrancar la aplicacion.

    El mensaje nombra la variable y, si es secreta, la posicion y el largo de
    la entrada que falla, nunca su valor.
    """
