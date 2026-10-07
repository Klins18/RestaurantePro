"""Unidades canónicas para evitar catálogos y movimientos duplicados por escritura."""
import unicodedata


UNIT_ALIASES = {
    'kg': ('kg', 'kgs', 'kilo', 'kilos', 'kilogramo', 'kilogramos'),
    'g': ('g', 'gr', 'grs', 'gramo', 'gramos'),
    'l': ('l', 'lt', 'lts', 'litro', 'litros'),
    'ml': ('ml', 'mililitro', 'mililitros'),
    'unidad': ('u', 'ud', 'uds', 'und', 'unid', 'unidad', 'unidades'),
    'caja': ('caja', 'cajas'),
    'bolsa': ('bolsa', 'bolsas'),
    'saco': ('saco', 'sacos'),
    'galon': ('galon', 'galones'),
    'atado': ('atado', 'atados'),
    'docena': ('docena', 'docenas'),
    'barra': ('barra', 'barras'),
    'sobre': ('sobre', 'sobres'),
    'paquete': ('paq', 'pqt', 'paquete', 'paquetes', 'pack'),
    'botella': ('botella', 'botellas'),
    'lata': ('lata', 'latas'),
    'arroba': ('@', 'arroba', 'arrobas'),
    'pan': ('pan', 'panes'),
    'S/.': ('s/.', 's/', 'sol', 'soles', 'monto'),
}


def _unit_key(value):
    text = unicodedata.normalize('NFKD', str(value or '').strip().casefold())
    return ''.join(char for char in text if not unicodedata.combining(char))


_CANONICAL_BY_ALIAS = {
    _unit_key(alias): canonical
    for canonical, aliases in UNIT_ALIASES.items()
    for alias in aliases
}


def normalize_unit(value):
    """Unifica alias conocidos y conserva unidades especiales no catalogadas."""
    original = str(value or '').strip()
    if not original:
        return ''
    return _CANONICAL_BY_ALIAS.get(_unit_key(original), original)


UNIT_CHOICES = [
    {'value': 'kg', 'label': 'Kilogramo (kg)'},
    {'value': 'g', 'label': 'Gramo (g)'},
    {'value': 'l', 'label': 'Litro (L)'},
    {'value': 'ml', 'label': 'Mililitro (ml)'},
    {'value': 'unidad', 'label': 'Unidad'},
    {'value': 'caja', 'label': 'Caja'},
    {'value': 'bolsa', 'label': 'Bolsa'},
    {'value': 'saco', 'label': 'Saco'},
    {'value': 'galon', 'label': 'Galón'},
    {'value': 'atado', 'label': 'Atado'},
    {'value': 'docena', 'label': 'Docena'},
    {'value': 'barra', 'label': 'Barra'},
    {'value': 'sobre', 'label': 'Sobre'},
    {'value': 'paquete', 'label': 'Paquete'},
    {'value': 'botella', 'label': 'Botella'},
    {'value': 'lata', 'label': 'Lata'},
    {'value': 'arroba', 'label': 'Arroba (@)'},
    {'value': 'pan', 'label': 'Pan'},
    {'value': 'S/.', 'label': 'Por monto (S/.)'},
]

INVENTORY_UNIT_CHOICES = [option for option in UNIT_CHOICES if option['value'] != 'S/.']
UNIT_LABELS = {option['value']: option['label'] for option in UNIT_CHOICES}


def unit_label(value):
    canonical = normalize_unit(value)
    return UNIT_LABELS.get(canonical, canonical)


def convert_quantity(quantity, source_unit, target_unit):
    """Convert a recipe quantity into the stock unit of an ingredient.

    Weight and volume units convert between metric scales. Individual items,
    bottles, cans and dozens use count conversions; packages such as boxes or
    bags convert only when their units match because their pack size varies.
    """
    source = normalize_unit(source_unit)
    target = normalize_unit(target_unit)
    value = float(quantity)
    if source == target:
        return value

    scales = {
        'g': ('weight', 1.0), 'kg': ('weight', 1000.0),
        'ml': ('volume', 1.0), 'l': ('volume', 1000.0),
        'unidad': ('count', 1.0), 'botella': ('count', 1.0),
        'lata': ('count', 1.0), 'docena': ('count', 12.0),
    }
    source_scale = scales.get(source)
    target_scale = scales.get(target)
    if source_scale and target_scale and source_scale[0] == target_scale[0]:
        return value * source_scale[1] / target_scale[1]
    raise ValueError(f'No se puede convertir {source or "(sin unidad)"} a {target or "(sin unidad)"}.')
