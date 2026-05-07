#!/usr/bin/env bash
# ShiftWise — quick cluster health check.
# Run from the bastion (10.9.21.150) with KUBECONFIG already exported.
# Usage:  bash cluster-health.sh
set -uo pipefail

: "${KUBECONFIG:=/root/openshift-install/config/auth/kubeconfig}"
export KUBECONFIG

hr() { printf '\n=== %s ===\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
ko() { printf '  ✗ %s\n' "$1"; }

hr "NODES"
oc get nodes

hr "OPERATORS (only unhealthy listed)"
bad=$(oc get co --no-headers | awk '$3!="True" || $4!="False" || $5!="False" {print $1}')
[ -z "$bad" ] && ok "all cluster operators healthy" || { ko "degraded:"; echo "$bad"; }

hr "ETCD"
etcd_pod=$(oc get pod -n openshift-etcd -l app=etcd -o name | head -1)
oc rsh -n openshift-etcd "$etcd_pod" etcdctl endpoint health --cluster 2>&1 | grep -E "healthy|unhealthy"

hr "FAILING PODS (cluster-wide)"
fail=$(oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null)
[ -z "$fail" ] && ok "no failing pods" || echo "$fail"

hr "STORAGE"
oc get sc | grep -E "NAME|nfs-client"
oc get pvc -A --no-headers 2>/dev/null | wc -l | xargs -I{} echo "  PVCs bound: {}"

hr "CNV / KUBEVIRT"
oc get csv -n openshift-cnv --no-headers | awk '{print "  "$1" → "$NF}'
hco_avail=$(oc get hyperconverged -n openshift-cnv -o jsonpath='{.items[0].status.conditions[?(@.type=="Available")].status}')
hco_degr=$(oc get hyperconverged -n openshift-cnv -o jsonpath='{.items[0].status.conditions[?(@.type=="Degraded")].status}')
echo "  HCO Available=$hco_avail Degraded=$hco_degr"
echo "  KubeVirt phase: $(oc get kubevirt -n openshift-cnv -o jsonpath='{.items[0].status.phase}')"
echo "  CDI phase:      $(oc get cdi      -n openshift-cnv -o jsonpath='{.items[0].status.phase}')"

hr "CAPACITY"
oc adm top nodes 2>/dev/null || ko "metrics-server not ready"

hr "SHIFTWISE NAMESPACE"
oc get ns shiftwise >/dev/null 2>&1 && ok "ns shiftwise exists" || ko "ns shiftwise missing — run: oc create ns shiftwise"
oc get all -n shiftwise --no-headers 2>/dev/null | wc -l | xargs -I{} echo "  resources in shiftwise: {}"

hr "BASTION SERVICES"
systemctl is-active named    >/dev/null && ok "named active"   || ko "named down"
systemctl is-active haproxy  >/dev/null && ok "haproxy active" || ko "haproxy down"
chronyc tracking 2>/dev/null | awk -F': ' '/Leap status/ {print "  NTP "$2}'

hr "DNS"
api_ip=$(dig +short api.migration.nextstep-it.com)
app_ip=$(dig +short console-openshift-console.apps.migration.nextstep-it.com)
echo "  api → ${api_ip:-FAIL}    *.apps → ${app_ip:-FAIL}"

echo
echo "Done."
