
## Git identity (required — read before committing)

All commits in this repo MUST be authored as the repo owner:

    git config user.name "kalepasch1"
    git config user.email "kalepasch@gmail.com"

Run this immediately after cloning, before your first commit. Vercel blocks
production deployments whose commit author is anyone else — commits authored
as e.g. mandyjustinepasch@gmail.com or kale@heretomorrow.us end up in BLOCKED
state and never deploy. Do not use your platform account identity.
