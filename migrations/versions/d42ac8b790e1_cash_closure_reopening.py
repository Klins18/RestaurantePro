"""Track deliberate reopening of a daily cash closure.

Revision ID: d42ac8b790e1
Revises: c91d72e8340a
"""
from alembic import op
import sqlalchemy as sa


revision = 'd42ac8b790e1'
down_revision = 'c91d72e8340a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cierres_caja') as batch_op:
        batch_op.add_column(sa.Column(
            'abierta', sa.Boolean(), nullable=False, server_default=sa.false()
        ))
        batch_op.add_column(sa.Column('reabierta_en', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reabierta_por_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('motivo_reapertura', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cierres_caja_reabierta_por_id_usuarios',
            'usuarios', ['reabierta_por_id'], ['id'],
        )


def downgrade():
    with op.batch_alter_table('cierres_caja') as batch_op:
        batch_op.drop_constraint(
            'fk_cierres_caja_reabierta_por_id_usuarios', type_='foreignkey'
        )
        batch_op.drop_column('motivo_reapertura')
        batch_op.drop_column('reabierta_por_id')
        batch_op.drop_column('reabierta_en')
        batch_op.drop_column('abierta')
