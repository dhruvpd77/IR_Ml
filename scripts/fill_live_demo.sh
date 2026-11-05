#!/bin/bash
# Fill a new live site with demo users and fake machines.
# Safe to run again: if machines already exist, it leaves them alone.
set -e
cd "$(dirname "$0")/.."
if [ -f "$HOME/.virtualenvs/irmqms/bin/activate" ]; then
  source "$HOME/.virtualenvs/irmqms/bin/activate"
fi
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
