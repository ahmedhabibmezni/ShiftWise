#!/bin/bash

echo "============================================"
echo "   VALIDATION HAProxy LOAD BALANCER"
echo "============================================"

# 1. Service status
echo -e "\n1. HAProxy Service Status:"
systemctl is-active haproxy

# 2. Ports en écoute
echo -e "\n2. Ports en écoute (attendus: 80, 443, 6443, 22623, 9000):"
ss -tlnp | grep haproxy | awk '{print $4}' | sort -u

# 3. Test de connexion aux frontends
echo -e "\n3. Test de connexion aux frontends:"
for port in 80 443 6443 22623 9000; do
    nc -zv 10.9.21.150 $port 2>&1 | grep -q succeeded && echo "   Port $port: OK" || echo "   Port $port: FAILED"
done

# 4. Stats HAProxy
echo -e "\n4. HAProxy Stats disponible sur:"
echo "   http://10.9.21.150:9000"
echo "   User: admin / Password: admin"

# 5. Vérifier la résolution DNS des backends
echo -e "\n5. Résolution DNS des backends:"
for host in bootstrap node01 node02 node03; do
    ip=$(dig +short ${host}.migration.nextstep-it.com @10.9.21.150 | head -1)
    echo "   ${host}.migration.nextstep-it.com -> $ip"
done

# 6. Configuration valide
echo -e "\n6. Validation configuration:"
haproxy -c -f /etc/haproxy/haproxy.cfg && echo "   Configuration: VALID" || echo "   Configuration: INVALID"

echo -e "\n============================================"