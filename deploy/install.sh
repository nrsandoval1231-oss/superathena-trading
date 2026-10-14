#!/usr/bin/env bash
# Install a reviewed checkout on Ubuntu; leave activation to the configured launch step.
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then
  echo 'Run this installer as root on the trading host.' >&2
  exit 2
fi
athena_repo=/opt/athena-trading
athena_expected_revision=${1:?Pass the exact reviewed Git commit SHA}
if [[ ! $athena_expected_revision =~ ^[a-f0-9]{40}$ ]]; then
  echo 'Expected a full Git commit SHA.' >&2
  exit 2
fi
if [[ $(git -C "$athena_repo" rev-parse HEAD) != "$athena_expected_revision" ]] ||
   [[ -n $(git -C "$athena_repo" status --porcelain) ]]; then
  echo 'The checkout must be clean and match the reviewed revision.' >&2
  exit 2
fi
if systemctl is-active --quiet athena-paper.service; then
  echo 'Stop and reconcile the running service before replacing its installation.' >&2
  exit 2
fi
if systemctl is-active --quiet athena-earnings.service; then
  echo 'Stop and reconcile athena-earnings.service before replacing its installation.' >&2
  exit 2
fi
apt-get update
apt-get install -y python3 python3-venv
if ! id athena >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/athena --shell /usr/sbin/nologin athena
fi
install -d -m 0700 -o athena -g athena /var/lib/athena
install -d -m 0700 -o athena -g athena /var/lib/athena/learning
install -d -m 0700 -o athena -g athena /var/lib/athena-earnings
install -d -m 0700 -o athena -g athena /var/lib/athena-risk
install -d -m 0700 /etc/athena
python3 -m venv "$athena_repo/.venv"
"$athena_repo/.venv/bin/python" -m pip install "$athena_repo"
install -m 0644 "$athena_repo/deploy/athena-paper.service" /etc/systemd/system/athena-paper.service
install -m 0644 "$athena_repo/deploy/athena-earnings.service" /etc/systemd/system/athena-earnings.service
if [[ ! -f /etc/athena/paper.env ]]; then
  install -m 0600 "$athena_repo/deploy/paper.env.example" /etc/athena/paper.env
fi
if [[ ! -f /etc/athena/earnings.env ]]; then
  install -m 0600 "$athena_repo/deploy/earnings.env.example" /etc/athena/earnings.env
fi
systemctl daemon-reload
echo 'Installed. Configure the secret environment, run preflight, then enable athena-paper.service.'
echo 'athena-earnings.service is installed and left stopped. Enable it only after its own preflight.'
