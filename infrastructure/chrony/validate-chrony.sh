#!/bin/bash

echo "============================================"
echo "   VALIDATION CHRONY TIME SYNCHRONIZATION"
echo "============================================"
echo ""

# 1. Service Status
echo "1. Chrony Service Status:"
systemctl is-active chronyd
if systemctl is-active --quiet chronyd; then
    echo "   ✓ Service actif"
else
    echo "   ✗ Service inactif"
fi
echo ""

# 2. NTP Sources
echo "2. NTP Sources:"
chronyc sources | tail -n +3
SOURCE_COUNT=$(chronyc sources | tail -n +3 | wc -l)
echo "   Nombre de sources: $SOURCE_COUNT (attendu: >= 2)"
echo ""

# 3. Current Sync Status
echo "3. Synchronization Status:"
chronyc tracking | grep "Reference ID"
chronyc tracking | grep "Stratum"
chronyc tracking | grep "System time"
chronyc tracking | grep "Last offset"
echo ""

# 4. Time Status
echo "4. System Time Status:"
timedatectl status | grep "System clock synchronized"
timedatectl status | grep "NTP service"
echo ""

# 5. Check Offset
echo "5. Time Offset Check:"
OFFSET=$(chronyc tracking | grep "System time" | awk '{print $4}')
echo "   Current offset: $OFFSET"
echo "   ✓ Acceptable if < 1000ms (1 second)"
echo ""

# 6. Check Stratum
echo "6. Stratum Level:"
STRATUM=$(chronyc tracking | grep "Stratum" | awk '{print $3}')
echo "   Current stratum: $STRATUM"
echo "   ✓ Acceptable if <= 4"
echo ""

# 7. Network Configuration
echo "7. Network NTP Configuration (allow subnet):"
grep "^allow" /etc/chrony.conf || echo "   No 'allow' directive found"
echo ""

# 8. Active Source
echo "8. Currently Active Source:"
chronyc sources | grep "^\^*" || echo "   No active source yet (synchronizing...)"
echo ""

# 9. Test NTP Port
echo "9. NTP Port (123) Listening:"
ss -tulpn | grep ":123" || echo "   Port 123 not listening"
echo ""

echo "============================================"
echo "   RÉSUMÉ:"
echo "============================================"
echo "✓ Service: $(systemctl is-active chronyd)"
echo "✓ Sources: $SOURCE_COUNT"
echo "✓ Stratum: $STRATUM"
echo "✓ NTP Active: $(timedatectl status | grep 'NTP service' | awk '{print $3}')"
echo "============================================"