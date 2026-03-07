#!/bin/bash

echo "============================================"
echo "   VALIDATION SERVEUR HTTP (httpd)"
echo "============================================"

# 1. Service status
echo -e "\n1. httpd Service Status:"
systemctl is-active httpd && echo "   ✓ Service actif" || echo "   ✗ Service inactif"

# 2. Port en écoute
echo -e "\n2. Port 8080 en écoute:"
ss -tlnp | grep :8080 | grep httpd && echo "   ✓ Port 8080 OK" || echo "   ✗ Port 8080 non disponible"

# 3. Configuration Listen
echo -e "\n3. Configuration Listen:"
grep "^Listen" /etc/httpd/conf/httpd.conf

# 4. Test HTTP local
echo -e "\n4. Test HTTP localhost:"
http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/)
if [ "$http_code" = "200" ] || [ "$http_code" = "403" ]; then
    echo "   ✓ HTTP localhost OK (code: $http_code)"
else
    echo "   ✗ HTTP localhost FAILED (code: $http_code)"
fi

# 5. Test HTTP externe
echo -e "\n5. Test HTTP externe (10.9.21.150:8080):"
http_code=$(curl -s -o /dev/null -w "%{http_code}" http://10.9.21.150:8080/)
if [ "$http_code" = "200" ] || [ "$http_code" = "403" ]; then
    echo "   ✓ HTTP externe OK (code: $http_code)"
else
    echo "   ✗ HTTP externe FAILED (code: $http_code)"
fi

# 6. Vérification structure des répertoires
echo -e "\n6. Structure des répertoires OpenShift:"
if [ -d "/var/www/html/openshift4" ]; then
    ls -l /var/www/html/openshift4/
    echo "   ✓ Répertoire openshift4 existe"
else
    echo "   ✗ Répertoire openshift4 manquant"
fi

# 7. URLs importantes
echo -e "\n7. URLs d'accès:"
echo "   - Racine: http://10.9.21.150:8080/"
echo "   - OpenShift: http://10.9.21.150:8080/openshift4/"
echo "   - Ignition: http://10.9.21.150:8080/openshift4/ignition/"
echo "   - RHCOS: http://10.9.21.150:8080/openshift4/rhcos/"

# 8. Récapitulatif des ports
echo -e "\n8. Récapitulatif des ports services:"
echo "   Port 80   -> HAProxy (Ingress HTTP)"
echo "   Port 443  -> HAProxy (Ingress HTTPS)"
echo "   Port 6443 -> HAProxy (Kubernetes API)"
echo "   Port 8080 -> httpd (Installation files)"
echo "   Port 9000 -> HAProxy (Stats)"
echo "   Port 22623 -> HAProxy (Machine Config)"

echo -e "\n============================================"