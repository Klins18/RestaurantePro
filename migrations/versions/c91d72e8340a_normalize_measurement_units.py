"""Unify spelling variants of measurement units in historical records.

Revision ID: c91d72e8340a
Revises: 7ac2f2541c21
"""
from alembic import op
import sqlalchemy as sa


revision = 'c91d72e8340a'
down_revision = '7ac2f2541c21'
branch_labels = None
depends_on = None


ALIASES = {
    'kg': ('kg', 'kgs', 'kilo', 'kilos', 'kilogramo', 'kilogramos'),
    'g': ('g', 'gr', 'grs', 'gramo', 'gramos'),
    'l': ('l', 'lt', 'lts', 'litro', 'litros'),
    'ml': ('ml', 'mililitro', 'mililitros'),
    'unidad': ('u', 'ud', 'uds', 'und', 'unid', 'unidad', 'unidades'),
    'caja': ('caja', 'cajas'),
    'bolsa': ('bolsa', 'bolsas'),
    'saco': ('saco', 'sacos'),
    'galon': ('galon', 'galones', 'galón'),
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


def upgrade():
    bind = op.get_bind()
    for table, column in (
        ('productos', 'unidad_medida'),
        ('movimientos_almacen', 'unidad_medida'),
        ('items_pedido', 'unidad_medida'),
        ('items_compra', 'unidad'),
        ('productos_recurrentes', 'unidad'),
    ):
        for canonical, aliases in ALIASES.items():
            # Lower(trim()) handles case and surrounding whitespace. Match
            # accented forms explicitly because portable SQL has no unaccent().
            placeholders = ', '.join(f':a{i}' for i in range(len(aliases)))
            params = {f'a{i}': alias.casefold() for i, alias in enumerate(aliases)}
            params['canonical'] = canonical
            bind.execute(sa.text(
                f'UPDATE {table} SET {column} = :canonical '
                f'WHERE lower(trim({column})) IN ({placeholders})'
            ), params)


def downgrade():
    # Original spellings cannot be reconstructed after canonicalization.
    pass
