#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 && -d /run/systemd/system ]] || exit 1
install -d -m 0755 /var/log/ml-lab /etc/systemd/resolved.conf.d
exec > >(tee /var/log/ml-lab/service-cleanup.log) 2>&1
ss -tulpn
# Для одиночной учебной VM достаточно обычного DNS; multicast discovery не нужен.
cat > /etc/systemd/resolved.conf.d/00-ml-lab.conf <<'CONF'
[Resolve]
LLMNR=no
MulticastDNS=no
CONF
systemctl restart systemd-resolved
for unit in avahi-daemon.service avahi-daemon.socket cups.service cups.socket rpcbind.service rpcbind.socket; do
    if systemctl list-unit-files "${unit}" --no-legend | awk '{print $1}' | grep -qx "${unit}"; then
        systemctl disable --now "${unit}"
        echo "Disabled unnecessary discovery/printing/RPC service: ${unit}"
    fi
done
ss -tulpn

