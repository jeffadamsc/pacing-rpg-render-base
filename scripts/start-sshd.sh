#!/usr/bin/env bash
set -Eeuo pipefail

: "${SSH_PUBLIC_KEY:?SSH_PUBLIC_KEY is required}"
case "${SSH_PUBLIC_KEY}" in
  ssh-*) ;;
  *)
    printf 'invalid SSH public key\n' >&2
    exit 1
    ;;
esac
case "${SSH_PUBLIC_KEY}" in
  *$'\n'*|*$'\r'*)
    printf 'invalid SSH public key\n' >&2
    exit 1
    ;;
esac

umask 077
mkdir -p /root/.ssh /run/sshd
printf '%s\n' "${SSH_PUBLIC_KEY}" > /root/.ssh/authorized_keys
chmod 0700 /root/.ssh
chmod 0600 /root/.ssh/authorized_keys
ssh-keygen -A
exec /usr/sbin/sshd -D -e
