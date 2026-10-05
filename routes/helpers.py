def agrupar_por_categoria(productos, categoria_attr='categoria'):
    """Agrupa productos por el nombre de su categoría, incluidos los no clasificados."""
    grupos = {}
    for producto in productos:
        categoria = getattr(producto, categoria_attr, None)
        nombre = getattr(categoria, 'nombre', None) or 'Sin categoría'
        grupos.setdefault(nombre, []).append(producto)
    return list(grupos.items())
