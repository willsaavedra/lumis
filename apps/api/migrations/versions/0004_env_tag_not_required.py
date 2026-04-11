"""Make 'env' tag definition non-required for all existing tenants."""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The 'team' tag is now inherited automatically from team membership via the
    # RepoTag system; its required flag is kept as-is (still required so analysts
    # always know which team owns a repo).  'env' is optional because not all
    # repos are tied to a single deployment environment.
    op.execute(
        """
        UPDATE tag_definitions
        SET required = FALSE,
            updated_at = NOW()
        WHERE key = 'env'
          AND required = TRUE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tag_definitions
        SET required = TRUE,
            updated_at = NOW()
        WHERE key = 'env'
          AND required = FALSE
        """
    )
