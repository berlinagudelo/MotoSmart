"""datos adicionales en registros pendientes

Revision ID: c4d1f0a2b7e9
Revises: 36a8a89bf66c
Create Date: 2026-11-17 18:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d1f0a2b7e9'
down_revision: Union[str, None] = '36a8a89bf66c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('registros_pendientes', sa.Column('datos', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('registros_pendientes', 'datos')
