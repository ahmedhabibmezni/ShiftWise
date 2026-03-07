#!/bin/bash

echo "============================================"
echo "   VALIDATION CONFIGURATION DNS"
echo "============================================"

# Test service
echo -e "\n1. Service DNS Status:"
systemctl is-active named

# Test résolution nodes
echo -e "\n2. Résolution Nodes:"
for node in node01 node02 node03; do
    result=$(dig @10.9.21.150 ${node}.migration.nextstep-it.com +short)
    echo "   $node -> $result"
done

# Test API
echo -e "\n3. Résolution API:"
api=$(dig @10.9.21.150 api.migration.nextstep-it.com +short)
api_int=$(dig @10.9.21.150 api-int.migration.nextstep-it.com +short)
echo "   api -> $api"
echo "   api-int -> $api_int"

# Test wildcard
echo -e "\n4. Wildcard Apps:"
test_app=$(dig @10.9.21.150 test.apps.migration.nextstep-it.com +short)
echo "   *.apps -> $test_app"

# Test reverse
echo -e "\n5. Reverse DNS:"
reverse=$(dig @10.9.21.150 -x 10.9.21.151 +short)
echo "   10.9.21.151 -> $reverse"

# Test SRV
echo -e "\n6. SRV Records etcd:"
srv_count=$(dig @10.9.21.150 _etcd-server-ssl._tcp.migration.nextstep-it.com SRV +short | wc -l)
echo "   Nombre d'entrées SRV: $srv_count (attendu: 3)"

echo -e "\n============================================"