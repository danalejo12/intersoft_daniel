# InterSoft

InterSoft es una aplicación web desarrollada con Django para gestionar procesos de negocio como compras, carrito, marketplace y operaciones relacionadas.

## Funcionalidades principales

- Gestión de módulos de negocio
- Carrito de compras
- Marketplace
- Flujo de compras
- Integración con plantillas y archivos estáticos

## Requisitos

- Python 3.10 o superior
- Django y dependencias del archivo `requirements.txt`

## Instalación

```bash
pip install -r requirements.txt
```

## Configuración

1. Copia el archivo `.env.example` como `.env`.
2. Ajusta las variables de entorno necesarias.
3. Ejecuta migraciones.

## Ejecución

```bash
python intersoft/manage.py runserver
```

## Estructura general

- `intersoft/` - proyecto principal de Django
- `intersoft/core/` - lógica principal de la aplicación
- `intersoft/core/templates/` - plantillas HTML
- `intersoft/core/static/` - archivos estáticos

## Roadmap

- Mejorar la documentación técnica
- Añadir más pruebas automatizadas
- Mejorar la interfaz visual
- Preparar una versión más presentable para portafolio
