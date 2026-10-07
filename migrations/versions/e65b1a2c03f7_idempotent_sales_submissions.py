"""Make sale form retries idempotent.

Revision ID: e65b1a2c03f7
Revises: d42ac8b790e1
"""
from alembic import op
import sqlalchemy as sa


revision = 'e65b1a2c03f7'
down_revision = 'd42ac8b790e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'solicitudes_venta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=32), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    with op.batch_alter_table('ventas_diarias') as batch_op:
        batch_op.add_column(sa.Column('solicitud_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_ventas_diarias_solicitud_id_solicitudes_venta',
            'solicitudes_venta', ['solicitud_id'], ['id'],
        )
        batch_op.create_index('ix_ventas_solicitud', ['solicitud_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ventas_diarias') as batch_op:
        batch_op.drop_index('ix_ventas_solicitud')
        batch_op.drop_constraint(
            'fk_ventas_diarias_solicitud_id_solicitudes_venta', type_='foreignkey'
        )
        batch_op.drop_column('solicitud_id')
    op.drop_table('solicitudes_venta')
