"""Permitir categorías de bienes con el mismo nombre en áreas distintas.

Revision ID: 7ac2f2541c21
Revises: bcbf89d1e8f9
Create Date: 2026-10-07
"""
from alembic import op


revision = '7ac2f2541c21'
down_revision = 'bcbf89d1e8f9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        'categorias_bien',
        naming_convention={'uq': 'uq_%(table_name)s_%(column_0_name)s'},
    ) as batch_op:
        batch_op.drop_constraint('uq_categorias_bien_nombre', type_='unique')
        batch_op.create_unique_constraint(
            'uq_categoria_bien_area', ['nombre', 'area']
        )


def downgrade():
    raise RuntimeError(
        'No se puede volver a la restricción anterior si hay categorías con el '
        'mismo nombre en áreas distintas. Consolídalas manualmente primero.'
    )
